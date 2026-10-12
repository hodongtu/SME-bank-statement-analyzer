"""BRD 2.1 - is the data set representative enough to conclude on."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from src.agents.calculator.period import Period, monthly_sum
from src.facts import Facts
from src.types import Ledger, StatementFile, Transaction
from src.utils.numbers import month_label


SOURCE_NOTES = {"system": " (hệ thống T24)", "it_service": " (dịch vụ đọc tài liệu IT)"}


def inventory(statements: list[StatementFile], ledgers: dict[str, Ledger],
              filings: dict) -> list[dict]:
    rows = []
    for record in statements:
        rows.append({
            "source": f"Sao kê {record.bank}" + SOURCE_NOTES.get(record.source, ""), "file": record.filename,
            "account": ", ".join(record.accounts) or "—",
            "currency": ", ".join(record.currencies) or "—",
            "period": _span(record.period_start, record.period_end)
                      + ("" if record.period_declared else " (theo ngày giao dịch)"),
            "rows": record.row_count, "errors": "; ".join(record.errors) or "Không",
        })
    for ledger in ledgers.values():
        repaired = f"đã ghép lại {ledger.repaired_rows} dòng bị vỡ" if ledger.repaired_rows else ""
        rows.append({
            "source": f"Sổ chi tiết {ledger.account}", "file": ledger.filename, "account": "—",
            "currency": "VND", "period": _span(ledger.period_start, ledger.period_end),
            "rows": len(ledger.entries),
            "errors": "; ".join(filter(None, ledger.errors + [repaired])) or "Không",
        })
    for filing in filings.get("files", []):
        rows.append({"source": filing["label"], "file": filing["file"], "account": "—",
                     "currency": "VND", "period": filing["period"], "rows": filing["rows"],
                     "errors": filing["error"] or "Không"})
    return rows


def _span(start: date | None, end: date | None) -> str:
    if not start or not end:
        return "—"
    return f"{start:%d/%m/%Y} – {end:%d/%m/%Y}"


def balance_checks(transactions: list[Transaction], statements: list[StatementFile],
                   balances: dict[str, dict], tolerance: float) -> list[dict]:
    """Per account: transaction-level chain if the file has balances, else T24 open/close."""

    by_account: dict[str, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        by_account[txn.account].append(txn)
    results = []
    for account, items in sorted(by_account.items()):
        items.sort(key=lambda t: (t.source_file, t.row_no))
        chained = [t for t in items if t.balance_after is not None]
        if chained:
            errors = 0
            for previous, current in zip(chained, chained[1:]):
                signed = float(current.amount) * (1 if current.direction == "IN" else -1)
                if abs(float(previous.balance_after) + signed - float(current.balance_after)) > tolerance:
                    errors += 1
            checked = max(len(chained) - 1, 0)
            results.append({"account": account, "method": "Từng giao dịch theo cột số dư",
                            "checked": checked, "errors": errors,
                            "status": "Khớp" if errors == 0 else f"Lệch {errors} giao dịch"})
            continue
        known = balances.get(account) or {}
        opening, closing = known.get("opening"), known.get("closing")
        if opening is None or closing is None:
            results.append({"account": account, "method": "Không kiểm tra được",
                            "checked": 0, "errors": 0,
                            "status": "Sao kê không có cột số dư và chưa có số dư đầu/cuối kỳ từ T24"})
            continue
        net = sum(float(t.amount) * (1 if t.direction == "IN" else -1) for t in items)
        gap = opening + net - closing
        results.append({"account": account, "method": "Số dư đầu kỳ + phát sinh = số dư cuối kỳ (T24)",
                        "checked": 0, "errors": 0 if abs(gap) <= tolerance else 1,
                        "status": "Khớp" if abs(gap) <= tolerance else f"Lệch {gap:,.0f} đồng"})
    return results


def revenue_coverage(period: Period, transactions: list[Transaction], vat_out: dict[str, tuple],
                     reported_revenue: dict[int, float], settings: dict) -> tuple[float | None, str]:
    business = monthly_sum(transactions, set(settings["business_inflow_codes"]), "IN")
    months = [m for m in period.required if m in period.full]
    vat_months = [m for m in months if m in vat_out]
    if vat_months:
        reference = sum(vat_out[m][0] for m in vat_months)
        basis = f"doanh thu VAT {len(vat_months)} tháng ({month_label(vat_months[0])} – {month_label(vat_months[-1])})"
    else:
        vat_months = [m for m in months if int(m[:4]) in reported_revenue]
        if not vat_months:
            return None, "không có tờ khai VAT hay BCTC trùng kỳ sao kê"
        reference = sum(reported_revenue[int(m[:4])] / 12 for m in vat_months)
        basis = f"doanh thu BCTC phân bổ đều cho {len(vat_months)} tháng (ước tính)"
    if reference <= 0:
        return None, f"{basis} bằng 0"
    inflow = sum(business.get(m, 0.0) for m in vat_months)
    return inflow / reference * 100, basis


def assess(facts: Facts, settings: dict, has_statement: bool) -> dict:
    """Warning level and conclusion of BRD 2.1, from facts only."""

    rules = settings["coverage"]
    reasons: list[str] = []
    unchecked: list[str] = []
    if not has_statement:
        return {"level": "Cao", "conclusion": rules["conclusion_by_level"]["Cao"],
                "reasons": ["Hồ sơ không có sao kê đọc được"], "unchecked": []}

    missing = facts.get("stmt.missing_months") or []
    coverage = facts.get("stmt.revenue_coverage_pct")
    balance_error = facts.get("stmt.balance_error_pct")
    alerts = facts.get("fraud.alert_accounts")
    level = "Tốt"

    def raise_to(new: str, why: str) -> None:
        nonlocal level
        order = ("Tốt", "Trung bình", "Cao")
        if order.index(new) > order.index(level):
            level = new
        reasons.append(why)

    if len(missing) >= rules["high"]["missing_months_at_least"]:
        raise_to("Cao", f"thiếu {len(missing)} tháng sao kê")
    elif len(missing) >= rules["medium"]["missing_months_at_least"]:
        raise_to("Trung bình", f"thiếu {len(missing)} tháng sao kê")
    if facts.has("stmt.revenue_coverage_pct"):
        if coverage < rules["high"]["revenue_coverage_below_pct"]:
            raise_to("Cao", f"mức độ bao phủ doanh thu {coverage:.0f}% < {rules['high']['revenue_coverage_below_pct']}%")
        elif coverage < rules["medium"]["revenue_coverage_below_pct"]:
            raise_to("Trung bình", f"mức độ bao phủ doanh thu {coverage:.0f}% < {rules['medium']['revenue_coverage_below_pct']}%")
    else:
        unchecked.append(facts.reason("stmt.revenue_coverage_pct"))
    if facts.has("stmt.balance_error_pct") and balance_error > rules["high"]["balance_error_above_pct"]:
        raise_to("Cao", f"sai liên tục số dư ở {balance_error:.2f}% giao dịch")
    if not facts.has("stmt.balance_reconciled"):
        unchecked.append(facts.reason("stmt.balance_reconciled"))
    elif not facts.get("stmt.balance_reconciled"):
        raise_to("Cao", "có tài khoản không đối chiếu khớp số dư")
    if facts.has("fraud.alert_accounts"):
        if alerts:
            raise_to("Cao", "Fraud cảnh báo tài khoản " + ", ".join(alerts))
    else:
        unchecked.append(facts.reason("fraud.alert_accounts"))
    if facts.has("fraud.unscreened_accounts") and facts.get("fraud.unscreened_accounts"):
        raise_to("Trung bình", "tài khoản chưa qua xử lý của Fraud: "
                 + ", ".join(facts.get("fraud.unscreened_accounts")))

    conclusion = rules["conclusion_by_level"][level]
    if unchecked and conclusion == rules["conclusion_by_level"]["Tốt"]:
        conclusion = rules["conclusion_by_level"]["Trung bình"]
    return {"level": level, "conclusion": conclusion, "reasons": reasons, "unchecked": unchecked}
