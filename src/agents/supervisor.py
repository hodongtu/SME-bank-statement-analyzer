"""One cash-flow analysis run: the steps, and the graph that orders them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from src.agents.calculator import cashflow, coverage, partners, scoring, trend
from src.agents.calculator.period import build_period, in_window
from src.agents.transactions.counterparty import LENDER, RELATED, SELF, Directory, resolve
from src.agents.transactions.transaction_classification import classify
from src.facts import Facts
from src.agents.documents.document_classification import identify
from src.agents.documents.document_discovery import discover
from src.agents.extraction.ledger_extraction import read_ledger
from src.agents.transactions.normalize import drop_duplicates, pair_internal_transfers, split_currency
from src.agents.extraction.statement_extraction import read_statement
from src.settings import get_settings
from src.tools import blwl, cic, fraud, registry, t24, trade, virac
from src.types import AnalyzerState
from src.utils.reading.tax_xml import parse_tax_xml

NODE_ORDER = ("read_documents", "parse_documents", "collect_reference_data",
              "classify_transactions", "analyse", "lookup_partners", "grade", "render_report")
NOT_WIRED = "chưa kết nối nguồn dữ liệu"


@dataclass
class AnalyzerResult:
    report_markdown: str
    facts: Facts
    analysis: dict
    steps: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)


def _lookup(executor: Any, label: str, call: Callable[[], Any]) -> tuple[Any, str]:
    """(value, reason). A value of None always comes with the reason it is None."""

    if executor is None:
        return None, f"{label}: {NOT_WIRED}"
    try:
        return call(), ""
    except Exception as exc:                          # noqa: BLE001 - the reason must reach the report
        return None, f"{label} lỗi: {type(exc).__name__}: {exc}"[:200]


def _step(state: AnalyzerState, line: str) -> list[str]:
    return [*state.get("steps", []), line]


class BankStatementAnalyzer:
    def __init__(self, config: Any, settings: dict | None = None) -> None:
        self.config = config
        self.settings = settings or get_settings()
        graph = StateGraph(AnalyzerState)
        for name in NODE_ORDER:
            graph.add_node(name, getattr(self, f"_node_{name}"))
        graph.set_entry_point(NODE_ORDER[0])
        for left, right in zip(NODE_ORDER, NODE_ORDER[1:]):
            graph.add_edge(left, right)
        graph.add_edge(NODE_ORDER[-1], END)
        self.graph = graph.compile()

    # -- 1. dossier ----------------------------------------------------------

    def _node_read_documents(self, state: AnalyzerState) -> AnalyzerState:
        documents = discover(state["case_dir"])
        for document in documents:
            document.doc_type = identify(document, self.settings["document_types"])
        kinds = sorted({d.doc_type for d in documents})
        return {**state, "documents": documents,
                "steps": _step(state, f"Read dossier: {len(documents)} files, types {', '.join(kinds)}")}

    def _node_parse_documents(self, state: AnalyzerState) -> AnalyzerState:
        settings = self.settings
        base = settings["analysis"]["base_currency"]
        statements, transactions, ledgers = [], [], {}
        filings: dict[str, Any] = {"files": [], "vat_out": {}, "vat_in": {}, "reported_revenue": {},
                                   "taxpayer_name": "", "unread": []}
        labels = {k: v["label"] for k, v in settings["document_types"].items()}
        for document in state["documents"]:
            kind = document.doc_type
            if kind == "statement":
                record, rows = read_statement(document.path, settings["statement_formats"], base)
                statements.append(record)
                transactions.extend(rows)
            elif kind in ("ledger_131", "ledger_331"):
                ledger = read_ledger(document.path, kind[-3:])
                if ledger.account in ledgers:
                    ledger.errors.append(f"Hồ sơ có nhiều hơn một sổ {ledger.account}; chỉ dùng {ledgers[ledger.account].filename}")
                else:
                    ledgers[ledger.account] = ledger
            elif kind == "tax_xml":
                self._read_filing(document.path, filings)
            else:
                filings["unread"].append({"file": document.filename,
                                          "label": labels.get(kind, "Không nhận diện được loại hồ sơ")})
        transactions, duplicates = drop_duplicates(transactions)
        transactions, foreign = split_currency(transactions, base)
        return {**state, "statements": statements, "transactions": transactions, "ledgers": ledgers,
                "tax_filings": {**filings, "duplicates": duplicates, "foreign": len(foreign)},
                "steps": _step(state, f"Parse: {len(statements)} statements, {len(transactions)} transactions "
                                      f"({duplicates} duplicates dropped, {len(foreign)} foreign-currency), "
                                      f"ledgers {', '.join(sorted(ledgers)) or 'none'}, "
                                      f"{len(filings['files'])} tax XML filings")}

    @staticmethod
    def _read_filing(path: Path, filings: dict) -> None:
        result = parse_tax_xml(str(path))
        entry = {"file": path.name, "label": "Hồ sơ thuế XML", "period": "—", "rows": 0,
                 "error": result.error}
        if result.kind == "vat" and not result.error:
            entry["label"] = "Tờ khai thuế GTGT"
            months = sorted(result.vat_revenue)
            entry["period"] = ", ".join(months)
            entry["rows"] = len(months)
            for month, value in result.vat_revenue.items():
                key = f"{month[3:]}-{month[:2]}"
                if key not in filings["vat_out"] or filings["vat_out"][key][1]:
                    filings["vat_out"][key] = value
            for month, value in result.vat_purchases.items():
                key = f"{month[3:]}-{month[:2]}"
                if key not in filings["vat_in"] or filings["vat_in"][key][1]:
                    filings["vat_in"][key] = value
        elif result.kind == "financial_statement" and not result.error:
            entry["label"] = "Báo cáo tài chính"
            statement = result.financial_statement_extraction or {}
            income = statement.get("income_statement") or {}
            for label, _, *values in income.get("line_items", []):
                if label == "Doanh thu bán hàng và cung cấp dịch vụ":
                    for year_label, value in zip(income.get("years", []), values):
                        if value is not None:
                            filings["reported_revenue"][int(year_label.split()[-1])] = float(value)
            entry["period"] = (statement.get("reporting_period") or {}).get("period_label", "—")
            entry["rows"] = len(income.get("line_items", []))
        if result.taxpayer_name:
            filings["taxpayer_name"] = filings["taxpayer_name"] or result.taxpayer_name
        filings["files"].append(entry)

    # -- 2. customer reference data -------------------------------------------

    def _node_collect_reference_data(self, state: AnalyzerState) -> AnalyzerState:
        executor, tax_code = self.config.query_executor, state["tax_code"]

        def ask(tool, **extra):
            return lambda: tool.invoke({"tax_code": tax_code, "executor": executor, **extra})

        reference: dict[str, Any] = {"errors": {}}
        for key, label, tool in (("registry", "ĐKKD", registry.get_registration),
                                 ("t24_accounts", "T24", t24.get_t24_accounts),
                                 ("fraud", "Fraud", fraud.get_fraud_screening),
                                 ("cic", "CIC", cic.get_cic_debt),
                                 ("blwl", "BL/WL", blwl.get_blwl_hits),
                                 ("virac", "VIRAC", virac.get_virac_financials),
                                 ("trade", "XNK", trade.get_trade_turnover)):
            value, reason = _lookup(executor, label, ask(tool))
            reference[key] = value
            if reason:
                reference["errors"][key] = reason
        if reference["registry"] == {}:
            reference["registry"], reference["errors"]["registry"] = None, "ĐKKD không có dữ liệu cho mã số thuế này"

        balances: dict[str, dict] = {}
        for record in state["statements"]:
            for account in record.accounts:
                if not (record.period_start and record.period_end):
                    continue
                opening, _ = _lookup(executor, "T24", lambda a=account, d=record.period_start - timedelta(days=1):
                                     t24.get_t24_balance.invoke({"account": a, "day": d.isoformat(), "executor": executor}))
                closing, _ = _lookup(executor, "T24", lambda a=account, d=record.period_end:
                                     t24.get_t24_balance.invoke({"account": a, "day": d.isoformat(), "executor": executor}))
                balances[account] = {
                    "opening": opening.get("balance") if opening and opening.get("balance_date") == (record.period_start - timedelta(days=1)).isoformat() else None,
                    "closing": closing.get("balance") if closing and closing.get("balance_date") == record.period_end.isoformat() else None,
                }
        reference["balances"] = balances
        found = sum(1 for k in ("registry", "t24_accounts", "fraud", "cic", "blwl", "virac", "trade")
                    if reference[k] not in (None, [], {}))
        return {**state, "reference": reference,
                "steps": _step(state, f"Reference data: {found}/7 sources returned data")}

    # -- 3. classification ----------------------------------------------------

    def _customer_name(self, state: AnalyzerState) -> str:
        registry_row = state["reference"].get("registry") or {}
        ledger_names = [l.company for l in state["ledgers"].values() if l.company]
        return (registry_row.get("name") or state["tax_filings"].get("taxpayer_name")
                or (ledger_names[0] if ledger_names else ""))

    def _node_classify_transactions(self, state: AnalyzerState) -> AnalyzerState:
        reference, transactions = state["reference"], state["transactions"]
        own_accounts = {t.account for t in transactions}
        own_accounts |= {str(r.get("account_no")) for r in reference.get("t24_accounts") or []}
        directory = Directory(self.settings)
        name = self._customer_name(state)
        if name:
            directory.add(SELF, name, state["tax_code"], own_accounts, party_id="self")
        registry_row = reference.get("registry") or {}
        people = [registry_row.get("legal_representative")] + [m.get("name") for m in registry_row.get("members") or []]
        for person in filter(None, people):
            directory.add(RELATED, person)
        for row in reference.get("cic") or []:
            directory.add(LENDER, str(row.get("lender") or ""))
        for ledger in state["ledgers"].values():
            directory.add_ledger(ledger)

        pairs = pair_internal_transfers(transactions, own_accounts)
        for txn in transactions:
            if not txn.counterparty_id:
                resolve(txn, directory)
        classify(transactions, self.settings)
        model_calls = 0
        if self.config.classifier_llm is not None:
            from src.agents.transactions.llm_classifier import classify_remaining
            model_calls = classify_remaining(transactions, self.config, self.settings, name, directory)
        unknown = sum(1 for t in transactions if t.category in ("IN_10", "OUT_11"))
        return {**state, "analysis": {"customer_name": name, "internal_pairs": pairs,
                                      "model_calls": model_calls},
                "steps": _step(state, f"Classify: {len(transactions)} transactions, {pairs} internal pairs, "
                                      f"{unknown} unclassified, {model_calls} model calls")}

    # -- 4. analysis ----------------------------------------------------------

    def _node_analyse(self, state: AnalyzerState) -> AnalyzerState:
        settings, reference = self.settings, state["reference"]
        statements, transactions = state["statements"], state["transactions"]
        filings, ledgers = state["tax_filings"], state["ledgers"]
        period = build_period(statements, transactions, state.get("analysis_month", ""), settings)
        window = in_window(transactions, period)
        facts = Facts()
        analysis = dict(state["analysis"])

        missing_labels = [m for m in period.missing]
        facts.set("stmt.full_months", len([m for m in period.required if m in period.full]))
        if missing_labels:
            facts.set("stmt.missing_months", missing_labels)
        else:
            facts.set_empty("stmt.missing_months", "đủ các tháng yêu cầu")

        value, basis = coverage.revenue_coverage(period, window, filings["vat_out"], filings["reported_revenue"], settings)
        facts.set("stmt.revenue_coverage_pct", value, reason=basis) if value is not None else \
            facts.mark_missing("stmt.revenue_coverage_pct", basis)
        analysis["revenue_basis"] = basis

        checks = coverage.balance_checks(transactions, statements, reference["balances"],
                                         settings["analysis"]["balance_tolerance_vnd"])
        checked = sum(c["checked"] for c in checks)
        if checked:
            facts.set("stmt.balance_error_pct", sum(c["errors"] for c in checks if c["checked"]) / checked * 100)
        else:
            facts.mark_missing("stmt.balance_error_pct", "sao kê không có cột số dư để kiểm tra từng giao dịch")
        unverifiable = [c["account"] for c in checks if c["method"] == "Không kiểm tra được"]
        if not checks:
            facts.mark_missing("stmt.balance_reconciled", "không có giao dịch")
        elif unverifiable:
            facts.mark_missing("stmt.balance_reconciled", "không đối chiếu được tài khoản " + ", ".join(unverifiable))
        else:
            facts.set("stmt.balance_reconciled", all(c["errors"] == 0 for c in checks))

        accounts = sorted({t.account for t in transactions})
        if reference.get("fraud") is None:
            reason = reference["errors"].get("fraud", NOT_WIRED)
            facts.mark_missing("fraud.alert_accounts", reason)
            facts.mark_missing("fraud.unscreened_accounts", reason)
        else:
            screened = {str(r.get("account_no")) for r in reference["fraud"]}
            alerts = [f"{r['account_no']} ({r.get('note') or 'không có ghi chú'})" for r in reference["fraud"]
                      if str(r.get("alert") or "").strip().lower() not in ("", "không", "khong")]
            unscreened = [a for a in accounts if a not in screened]
            facts.set("fraud.alert_accounts", alerts) if alerts else facts.set_empty("fraud.alert_accounts", "không có cảnh báo")
            facts.set("fraud.unscreened_accounts", unscreened) if unscreened else \
                facts.set_empty("fraud.unscreened_accounts", "mọi tài khoản đã qua xử lý")
        if reference.get("t24_accounts") is None:
            facts.mark_missing("t24.accounts_without_statement", reference["errors"].get("t24_accounts", NOT_WIRED))
        else:
            absent = [str(r["account_no"]) for r in reference["t24_accounts"] if str(r["account_no"]) not in accounts]
            facts.set("t24.accounts_without_statement", absent) if absent else \
                facts.set_empty("t24.accounts_without_statement", "mọi tài khoản tại TCB đều có sao kê")

        openings = {a: float(b["opening"]) for a, b in reference["balances"].items() if b.get("opening") is not None}
        supplier = partners.top_partners("supplier", window, transactions, statements, ledgers, settings)
        customer = partners.top_partners("customer", window, transactions, statements, ledgers, settings)
        flows_full = sum(float(t.amount) for t in window if t.day.strftime("%Y-%m") in period.full)
        yearly_flows = flows_full / len(period.full) * 12 if period.full else 0.0

        measured = {
            "score.inflow_to_reported_revenue": scoring.inflow_to_reported_revenue(transactions, statements, filings["reported_revenue"], settings),
            "score.vat_gap": scoring.vat_gap(window, period, filings["vat_out"], settings),
            "score.inflow_matched_131": scoring.matched_131(window, "131" in ledgers),
            "score.unclassified_share": scoring.unclassified_share(window),
            "score.reported_vs_third_party": scoring.reported_vs_third_party(filings["reported_revenue"], reference.get("virac")),
            "score.trade_industry_legal": scoring.trade_industry_legal(
                reference.get("registry"), reference.get("blwl"), reference.get("trade"),
                yearly_flows, self.config.manual_trade_assessment),
        }
        notes = {}
        for path, (value, note) in measured.items():
            notes[path] = note
            if value is None:
                facts.mark_missing(path, note)
            else:
                facts.set(path, value)
        if filings["reported_revenue"]:
            facts.set("pillar.financial_statement", True)
        else:
            facts.mark_missing("pillar.financial_statement", "không có BCTC đọc được")
        vat_months = [m for m in period.required if m in filings["vat_out"]]
        if len(vat_months) >= settings["analysis"]["vat_required_months"]:
            facts.set("pillar.vat_12m", True)
        else:
            facts.mark_missing("pillar.vat_12m", f"tờ khai VAT chỉ phủ {len(vat_months)}/"
                                                 f"{settings['analysis']['vat_required_months']} tháng yêu cầu")

        analysis.update({
            "period": period, "window_count": len(window),
            "outside_window": len(transactions) - len(window),
            "inventory": coverage.inventory(statements, ledgers, filings),
            "balance_checks": checks,
            "matrix": cashflow.category_matrix(window, period),
            "label_sources": cashflow.label_sources(window),
            "largest_unclassified": cashflow.largest_unclassified(window),
            "overview": trend.overview(window, statements, openings, period, settings),
            "vat": trend.vat_comparison(window, period, filings["vat_in"], filings["vat_out"]),
            "partners": {"supplier": supplier, "customer": customer},
            "indicator_notes": notes,
        })
        return {**state, "facts": facts, "analysis": analysis,
                "steps": _step(state, f"Analyse: window {period.window[0] if period.window else '-'} to "
                                      f"{period.current or '-'}, {len(period.full)} full months, {len(window)} transactions in window")}

    # -- 5. counterparty lookups ----------------------------------------------

    def _node_lookup_partners(self, state: AnalyzerState) -> AnalyzerState:
        executor = self.config.query_executor
        looked = 0
        for side in state["analysis"]["partners"].values():
            for row in side["rows"]:
                if not row["tax_code"] or executor is None:
                    row["lookup"] = None
                    continue
                code = row["tax_code"]

                def ask(tool, code=code):
                    return lambda: tool.invoke({"tax_code": code, "executor": executor})

                info = {}
                for key, label, tool in (("blwl", "BL/WL", blwl.get_blwl_hits),
                                         ("virac", "VIRAC", virac.get_virac_financials),
                                         ("cic", "CIC", cic.get_cic_debt),
                                         ("trade", "XNK", trade.get_trade_turnover)):
                    info[key], _ = _lookup(executor, label, ask(tool))
                row["lookup"] = info
                looked += 1
        return {**state, "steps": _step(state, f"Counterparty lookups: {looked} counterparties with a tax code")}

    # -- 6. conclusions -------------------------------------------------------

    def _node_grade(self, state: AnalyzerState) -> AnalyzerState:
        facts, analysis = state["facts"], dict(state["analysis"])
        assessment = coverage.assess(facts, self.settings, bool(state["transactions"]))
        insufficient = self.settings["coverage"]["conclusion_by_level"]["Cao"]
        if assessment["conclusion"] != insufficient:
            facts.set("pillar.representative_statement", True)
        else:
            facts.mark_missing("pillar.representative_statement",
                               "kết luận độ bao phủ là " + insufficient.lower())
        analysis["coverage"] = assessment
        analysis["score"] = scoring.grade(facts, self.settings)
        return {**state, "analysis": analysis,
                "steps": _step(state, f"Grade: coverage “{assessment['conclusion']}”, "
                                      f"revenue reliability “{analysis['score']['rating']}”")}

    def _node_render_report(self, state: AnalyzerState) -> AnalyzerState:
        from src.utils.report.render import render_report

        report = render_report(state, self.settings)
        return {**state, "report_markdown": report,
                "steps": _step(state, f"Render: {len(report):,} characters")}

    def run(self, case_dir: str | Path, tax_code: str, analysis_month: str = "",
            report_date: str = "") -> dict:
        return self.graph.invoke({"case_dir": str(case_dir), "tax_code": tax_code,
                                  "analysis_month": analysis_month, "report_date": report_date,
                                  "steps": []})


def run_analysis(case_dir: str | Path, config: Any, tax_code: str, analysis_month: str = "",
                 report_date: date | None = None) -> AnalyzerResult:
    """Analyse ONE customer's statements, from its upload folder to a Markdown report."""

    final = BankStatementAnalyzer(config).run(case_dir, tax_code, analysis_month,
                                     (report_date or date.today()).isoformat())
    return AnalyzerResult(report_markdown=final["report_markdown"], facts=final["facts"],
                          analysis=final["analysis"], steps=final["steps"], state=final)
