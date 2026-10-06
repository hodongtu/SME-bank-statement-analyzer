"""BRD 2.4 - scale, trend and stability of the cash flow; VAT comparison."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from src.agents.calculator.period import Period, monthly_sum
from src.types import StatementFile, Transaction
from src.utils.numbers import month_key


def trend_label(recent: float | None, average: float | None, settings: dict) -> str:
    if recent is None or average is None or average == 0:
        return "—"
    change = (recent - average) / abs(average) * 100
    rules = settings["trend"]
    if change > rules["up_above_pct"]:
        return f"Tăng ({change:+.0f}%)"
    if change < rules["down_below_pct"]:
        return f"Giảm ({change:+.0f}%)"
    return f"Ổn định ({change:+.0f}%)"


def _flow_row(label: str, monthly: dict[str, float], period: Period, settings: dict) -> dict:
    full = period.full
    recent = settings["trend"]["recent_months"]
    total = sum(monthly.get(m, 0.0) for m in period.window)
    average = sum(monthly.get(m, 0.0) for m in full) / len(full) if full else None
    last3 = full[-recent:]
    last6 = full[-6:]
    avg3 = sum(monthly.get(m, 0.0) for m in last3) / len(last3) if last3 else None
    avg6 = sum(monthly.get(m, 0.0) for m in last6) / len(last6) if last6 else None
    return {"label": label, "total": total, "average": average, "last3": avg3, "last6": avg6,
            "trend": trend_label(avg3, average, settings)}


def daily_balances(transactions: list[Transaction], statements: list[StatementFile],
                   openings: dict[str, float]) -> tuple[dict[date, float], list[str]]:
    """Summed end-of-day balance over every account whose balance is known."""

    periods: dict[str, tuple[date, date]] = {}
    for record in statements:
        for account in record.accounts:
            start, end = periods.get(account, (record.period_start, record.period_end))
            periods[account] = (min(start, record.period_start), max(end, record.period_end))
    by_account: dict[str, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        by_account[txn.account].append(txn)

    totals: dict[date, float] = defaultdict(float)
    unknown: list[str] = []
    for account, (start, end) in sorted(periods.items()):
        items = sorted(by_account.get(account, []), key=lambda t: (t.source_file, t.row_no))
        chained = [t for t in items if t.balance_after is not None]
        if chained:
            first = chained[0]
            balance = float(first.balance_after) - float(first.amount) * (1 if first.direction == "IN" else -1)
            closing_by_day = {t.day: float(t.balance_after) for t in chained}
            flows = None
        elif account in openings:
            balance = openings[account]
            closing_by_day = None
            flows: dict[date, float] = defaultdict(float)
            for t in items:
                flows[t.day] += float(t.amount) * (1 if t.direction == "IN" else -1)
        else:
            unknown.append(account)
            continue
        day = start
        while day <= end:
            if closing_by_day is not None:
                balance = closing_by_day.get(day, balance)
            else:
                balance += flows.get(day, 0.0)
            totals[day] += balance
            day += timedelta(days=1)
    return dict(totals), unknown


def _balance_row(balances: dict[date, float], period: Period, settings: dict) -> dict:
    def average(months: list[str]) -> float | None:
        values = [v for d, v in balances.items() if month_key(d) in months]
        return sum(values) / len(values) if values else None

    full = period.full
    monthly = [average([m]) for m in full]
    monthly = [v for v in monthly if v is not None]
    recent = settings["trend"]["recent_months"]
    avg3, avg_month = average(full[-recent:]), (sum(monthly) / len(monthly) if monthly else None)
    return {"label": "Số dư cuối ngày bình quân", "total": average(period.window),
            "average": avg_month, "last3": avg3, "last6": average(full[-6:]),
            "trend": trend_label(avg3, avg_month, settings)}


def overview(transactions: list[Transaction], statements: list[StatementFile],
             openings: dict[str, float], period: Period, settings: dict) -> dict:
    sales = monthly_sum(transactions, {"IN_01"}, "IN")
    spending = monthly_sum(transactions, set(settings["business_outflow_codes"]), "OUT")
    net = {m: sales.get(m, 0.0) - spending.get(m, 0.0) for m in period.window}
    rows = [
        _flow_row("Tiền thu từ bán hàng, cung cấp dịch vụ", sales, period, settings),
        _flow_row("Thanh toán cho NCC và thanh toán các chi phí HĐKD", spending, period, settings),
        _flow_row("Dòng tiền thuần (dòng 1 trừ dòng 2)", net, period, settings),
    ]
    balances, unknown = daily_balances(transactions, statements, openings)
    if unknown or not balances:
        rows.append({"label": "Số dư cuối ngày bình quân", "unavailable":
                     "chưa có số dư đầu kỳ cho tài khoản " + ", ".join(unknown) if unknown
                     else "không có dữ liệu số dư"})
    else:
        rows.append(_balance_row(balances, period, settings))
    return {"rows": rows, "full_months": len(period.full)}


def vat_comparison(transactions: list[Transaction], period: Period,
                   vat_in: dict[str, tuple], vat_out: dict[str, tuple]) -> dict:
    inflow = monthly_sum(transactions, direction="IN")
    outflow = monthly_sum(transactions, direction="OUT")
    rows = []
    for month in period.required:
        purchases, sales = vat_in.get(month), vat_out.get(month)
        rows.append({
            "month": month, "full": month in period.full,
            "vat_in": purchases[0] if purchases else None,
            "vat_in_estimated": bool(purchases and purchases[1]),
            "outflow": outflow.get(month, 0.0),
            "vat_out": sales[0] if sales else None,
            "vat_out_estimated": bool(sales and sales[1]),
            "inflow": inflow.get(month, 0.0),
        })
    return {"rows": rows, "has_vat": any(r["vat_out"] is not None for r in rows)}
