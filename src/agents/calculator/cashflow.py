"""BRD 2.3 - cash flow by economic nature, category x month."""

from __future__ import annotations

from collections import defaultdict

from src.agents.calculator.period import Period
from src.categories import INFLOW, OUTFLOW
from src.agents.transactions.transaction_classification import SOURCE_ORDER
from src.types import Transaction
from src.utils.numbers import month_key


def category_matrix(transactions: list[Transaction], period: Period) -> dict:
    cells: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for txn in transactions:
        cells[txn.category][month_key(txn.day)] += float(txn.amount)

    def block(codes: dict[str, str]) -> dict:
        rows = []
        for code, label in codes.items():
            values = [cells[code].get(m, 0.0) for m in period.window]
            rows.append({"code": code, "label": label, "values": values, "total": sum(values)})
        totals = [sum(r["values"][i] for r in rows) for i in range(len(period.window))]
        return {"rows": rows, "totals": totals, "grand_total": sum(totals)}

    return {"months": period.window, "inflow": block(INFLOW), "outflow": block(OUTFLOW)}


def label_sources(transactions: list[Transaction]) -> list[dict]:
    """How much of the money each kind of evidence classified."""

    total = sum(float(t.amount) for t in transactions) or 1.0
    by_source: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for txn in transactions:
        by_source[txn.label_source][0] += 1
        by_source[txn.label_source][1] += float(txn.amount)
    return [{"source": source, "count": int(by_source[source][0]), "value": by_source[source][1],
             "share": by_source[source][1] / total * 100}
            for source in SOURCE_ORDER if source in by_source]


def largest_unclassified(transactions: list[Transaction], limit: int = 10) -> list[Transaction]:
    unknown = [t for t in transactions if t.category in ("IN_10", "OUT_11")]
    return sorted(unknown, key=lambda t: t.amount, reverse=True)[:limit]
