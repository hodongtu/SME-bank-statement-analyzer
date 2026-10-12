"""One cash-flow analysis run: the steps, and the graph that orders them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from src.agents.calculator import cashflow, coverage, partners, scoring, trend
from src.agents.calculator.period import analysis_window, build_period, in_window
from src.agents.transactions.counterparty import LENDER, RELATED, SELF, Directory, resolve
from src.agents.transactions.transaction_classification import classify
from src.facts import Facts
from src.agents.documents.document_classification import identify
from src.agents.documents.document_discovery import discover
from src.agents.extraction.contract import FAILED
from src.agents.extraction.router import ExtractionRouter
from src.agents.extraction.statement_extraction import transactions_from_records
from src.agents.transactions.normalize import drop_duplicates, pair_internal_transfers, split_currency
from src.settings import get_settings
from src.tools import blwl, cic, fraud, registry, t24, trade, virac
from src.tools.customer_keys import resolve_customer_key
from src.types import AnalyzerState, StatementFile
from src.utils.common import normalize_text

NODE_ORDER = ("read_documents", "parse_documents", "fetch_statements", "collect_reference_data",
              "classify_transactions", "analyse", "lookup_partners", "grade", "render_report")
SYSTEM_SOURCE = "Hệ thống T24"
UNREADABLE_FILE = "Không đọc được giao dịch; dùng dữ liệu hệ thống T24"
NOT_WIRED = "chưa kết nối nguồn dữ liệu"
FORMAT_RANK = {"xml": 0, "xlsx": 1, "xls": 1, "xlsm": 1, "pdf": 2}
NO_TAX_CODE = "chưa xác định được mã số thuế khách hàng"


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


def _is_tcb(record: StatementFile) -> bool:
    return record.format_id == "tcb_core" or "techcombank" in normalize_text(record.bank)


def _step(state: AnalyzerState, line: str) -> list[str]:
    return [*state.get("steps", []), line]


class BankStatementAnalyzer:
    def __init__(self, config: Any, settings: dict | None = None) -> None:
        self.config = config
        self.settings = settings or get_settings()
        self.router = getattr(config, "extraction_router", None) or ExtractionRouter(self.settings)
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
        statements, transactions, ledgers = [], [], {}
        filings: dict[str, Any] = {"files": [], "vat_out": {}, "vat_in": {}, "vat_rank": {}, "vat_in_rank": {},
                                   "reported_revenue": {}, "taxpayer_name": "", "unread": []}
        labels = {k: v["label"] for k, v in settings["document_types"].items()}
        self.router.reset()
        extracted_documents = []
        for document in state["documents"]:
            extracted = self.router.extract(document)
            extracted_documents.append(extracted)
            if extracted.statement is not None:
                extracted.statement.source = extracted.backend if extracted.backend != "local" else "file"
                statements.append(extracted.statement)
                transactions.extend(extracted.transactions)
            elif extracted.ledger is not None:
                ledger = extracted.ledger
                if ledger.account in ledgers:
                    ledger.errors.append(f"Hồ sơ có nhiều hơn một sổ {ledger.account}; chỉ dùng {ledgers[ledger.account].filename}")
                else:
                    ledgers[ledger.account] = ledger
            elif extracted.vat is not None or extracted.financials is not None or extracted.source_format == "xml":
                self._add_filing(extracted, filings)
            else:
                filings["unread"].append({"file": document.filename, "reason": extracted.reason,
                                          "label": labels.get(extracted.doc_type, "Không nhận diện được loại hồ sơ")})
        return {**state, "statements": statements, "transactions": transactions, "ledgers": ledgers,
                "extracted_documents": extracted_documents, "tax_filings": filings,
                "steps": _step(state, f"Parse: {len(statements)} statement files, {len(transactions)} transactions, "
                                      f"ledgers {', '.join(sorted(ledgers)) or 'none'}, "
                                      f"{len(filings['files'])} tax filings")}

    @staticmethod
    def _merge_vat(series: dict, ranks: dict, values: dict, rank: int) -> list[str]:
        """Monthly beats quarterly-estimated; at equal footing the better-ranked format wins."""

        clashes = []
        for month, value in values.items():
            current = series.get(month)
            if current is None or (current[1] and (not value[1] or rank < ranks[month])) \
                    or (current[1] == value[1] and rank < ranks[month]):
                if current is not None and not current[1] and not value[1] and abs(current[0] - value[0]) > 1:
                    clashes.append(month)
                series[month], ranks[month] = value, rank
            elif not current[1] and not value[1] and abs(current[0] - value[0]) > 1:
                clashes.append(month)
        return clashes

    def _add_filing(self, extracted: Any, filings: dict) -> None:
        vat, financials = extracted.vat, extracted.financials
        label = {"vat_return": "Tờ khai thuế GTGT", "financial_statement": "Báo cáo tài chính"}.get(
            extracted.doc_type, "Hồ sơ thuế XML")
        if extracted.status == FAILED and extracted.source_format == "xml":
            label = "Hồ sơ thuế XML"
        if extracted.backend != "local":
            label += " (dịch vụ đọc tài liệu IT)"
        entry = {"file": extracted.document.filename, "label": label, "period": "—", "rows": 0,
                 "error": extracted.reason if extracted.status == FAILED else "",
                 "kind": extracted.doc_type, "format": extracted.source_format,
                 "tax_code": extracted.tax_code, "taxpayer_name": extracted.taxpayer_name}
        if vat is not None:
            entry["period"], entry["rows"] = vat.period_label, len(vat.revenue)
            rank = FORMAT_RANK.get(vat.source_format, len(FORMAT_RANK))
            clashes = self._merge_vat(filings["vat_out"], filings["vat_rank"], vat.revenue, rank)
            self._merge_vat(filings["vat_in"], filings["vat_in_rank"], vat.purchases, rank)
            if clashes:
                entry["error"] = ("Trùng tháng " + ", ".join(f"{m[5:]}/{m[:4]}" for m in sorted(clashes))
                                  + " với tờ khai khác có số liệu khác; dùng nguồn ưu tiên hơn")
        elif financials is not None:
            entry["period"], entry["rows"] = financials.period_label, financials.line_count
            filings["reported_revenue"].update(financials.revenue_by_year)
        if extracted.taxpayer_name:
            filings["taxpayer_name"] = filings["taxpayer_name"] or extracted.taxpayer_name
        filings["files"].append(entry)

    # -- 2. TCB statements from the system --------------------------------------

    def _node_fetch_statements(self, state: AnalyzerState) -> AnalyzerState:
        settings, executor = self.settings, self.config.query_executor
        base = settings["analysis"]["base_currency"]
        key = resolve_customer_key(state["tax_filings"]["files"], state.get("tax_code", ""))
        steps = [*state.get("steps", []), *(f"Customer key: {warning}" for warning in key.warnings)]
        if key.usable:
            steps.append(f"Customer key: tax code {key.tax_code} from {key.source_file} ({key.source_field})")
        report_date = date.fromisoformat(state["report_date"]) if state.get("report_date") else date.today()
        start, end, month = analysis_window(report_date, state.get("analysis_month", ""), settings)

        statements, transactions = list(state["statements"]), list(state["transactions"])
        analysis_month = state.get("analysis_month", "")
        tcb_files = [r for r in statements if r.source == "file" and _is_tcb(r)]
        use_files = any(r.row_count for r in tcb_files)

        seed: dict[str, Any] = {"errors": {}}
        accounts, records, reason = None, [], ""
        if not key.usable:
            reason = f"Sao kê TCB: {NO_TAX_CODE}"
        else:
            accounts, reason = _lookup(executor, "T24", lambda: t24.get_t24_accounts.invoke(
                {"tax_code": key.tax_code, "executor": executor}))
            seed["t24_accounts"] = accounts
            if reason:
                seed["errors"]["t24_accounts"] = reason
            if use_files:
                reason = ""
            elif accounts:
                records, reason = _lookup(executor, "Sao kê TCB", lambda: t24.get_t24_transactions.invoke(
                    {"tax_code": key.tax_code, "date_from": start.isoformat(),
                     "date_to": (end + timedelta(days=1)).isoformat(), "executor": executor}))
            elif not reason:
                reason = "Sao kê TCB: T24 không có tài khoản nào cho mã số thuế này"

        if use_files:
            steps.append(f"TCB statements: {len(tcb_files)} uploaded file(s) used; T24 transactions not queried")
        elif accounts and not reason:
            spec = next(f for f in settings["statement_formats"] if f["id"] == "tcb_core")
            rows, errors = transactions_from_records(records, spec, "Techcombank", SYSTEM_SOURCE, base)
            for record in tcb_files:
                record.errors.append(UNREADABLE_FILE)
            for account in accounts:
                number = str(account["account_no"])
                opened = account.get("opened_on")
                own = [t for t in rows if t.account == number]
                statements.append(StatementFile(
                    filename=SYSTEM_SOURCE, bank="Techcombank", accounts=[number],
                    currencies=[str(account.get("currency") or base)],
                    period_start=max(start, date.fromisoformat(str(opened))) if opened else start,
                    period_end=end, period_declared=True, row_count=len(own), format_id="t24_query",
                    errors=list(errors), source="system"))
                transactions.extend(own)
            analysis_month = month
            steps.append(f"TCB statements from T24: {len(accounts)} accounts, {len(rows)} transactions, "
                         f"{start:%Y-%m-%d} to {end:%Y-%m-%d}")
        else:
            reason = reason or "T24 không trả về dữ liệu"
            detail = reason.removeprefix("Sao kê TCB: ")
            seed["errors"]["t24_transactions"] = f"Không có file sao kê TCB tải lên và không lấy được từ hệ thống ({detail})"
            steps.append(f"TCB statements: no uploaded file and T24 not available ({reason})")

        transactions, duplicates = drop_duplicates(transactions)
        transactions, foreign = split_currency(transactions, base)
        steps.append(f"Merged: {len(transactions)} transactions ({duplicates} duplicates dropped, "
                     f"{len(foreign)} foreign-currency)")
        return {**state, "statements": statements, "transactions": transactions, "tax_code": key.tax_code,
                "customer_key": {**key._asdict(), "usable": key.usable}, "analysis_month": analysis_month,
                "reference": seed, "tax_filings": {**state["tax_filings"], "duplicates": duplicates,
                                                   "foreign": len(foreign)},
                "steps": steps}

    # -- 3. customer reference data -------------------------------------------

    def _node_collect_reference_data(self, state: AnalyzerState) -> AnalyzerState:
        executor = self.config.query_executor
        tax_code, usable = state.get("tax_code", ""), state.get("customer_key", {}).get("usable", False)
        steps = list(state.get("steps", []))

        def ask(tool, **extra):
            return lambda: tool.invoke({"tax_code": tax_code, "executor": executor, **extra})

        seed = state.get("reference") or {"errors": {}}
        reference: dict[str, Any] = {"errors": dict(seed.get("errors", {}))}
        for source, label, tool in (("registry", "ĐKKD", registry.get_registration),
                                    ("t24_accounts", "T24", t24.get_t24_accounts),
                                    ("fraud", "Fraud", fraud.get_fraud_screening),
                                    ("cic", "CIC", cic.get_cic_debt),
                                    ("blwl", "BL/WL", blwl.get_blwl_hits),
                                    ("virac", "VIRAC", virac.get_virac_financials),
                                    ("trade", "XNK", trade.get_trade_turnover)):
            if source in seed:
                reference[source] = seed[source]
                continue
            value, reason = (_lookup(executor, label, ask(tool)) if usable
                             else (None, f"{label}: {NO_TAX_CODE}"))
            reference[source] = value
            if reason:
                reference["errors"][source] = reason
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
        steps.append(f"Reference data: {found}/7 sources returned data")
        return {**state, "reference": reference, "steps": steps}

    # -- 4. classification ----------------------------------------------------

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

        accounts = sorted({a for record in statements for a in record.accounts} | {t.account for t in transactions})
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

    def run(self, case_dir: str | Path, tax_code: str = "", analysis_month: str = "",
            report_date: str = "") -> dict:
        return self.graph.invoke({"case_dir": str(case_dir), "tax_code": tax_code,
                                  "analysis_month": analysis_month, "report_date": report_date,
                                  "steps": []})


def run_analysis(case_dir: str | Path, config: Any, tax_code: str = "", analysis_month: str = "",
                 report_date: date | None = None) -> AnalyzerResult:
    """Analyse ONE customer's statements, from its upload folder to a Markdown report."""

    final = BankStatementAnalyzer(config).run(case_dir, tax_code, analysis_month,
                                     (report_date or date.today()).isoformat())
    return AnalyzerResult(report_markdown=final["report_markdown"], facts=final["facts"],
                          analysis=final["analysis"], steps=final["steps"], state=final)
