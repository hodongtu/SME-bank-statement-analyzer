"""BRD 2.5 - top counterparties by value, mapped to the 131 / 331 ledgers."""

from __future__ import annotations

from collections import Counter, defaultdict

from src.agents.calculator.period import full_months_between
from src.agents.transactions.counterparty import kind_of
from src.types import Ledger, StatementFile, Transaction

SIDES = {
    "supplier": {"category": "OUT_01", "ledger": "331", "basis": "debit"},
    "customer": {"category": "IN_01", "ledger": "131", "basis": "credit"},
}


def top_partners(side: str, window_txns: list[Transaction], all_txns: list[Transaction],
                 statements: list[StatementFile], ledgers: dict[str, Ledger],
                 settings: dict) -> dict:
    spec = SIDES[side]
    ledger = ledgers.get(spec["ledger"])
    chosen = [t for t in window_txns if t.category == spec["category"]]
    total_value = sum(float(t.amount) for t in chosen)

    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for txn in chosen:
        if txn.counterparty_id:
            grouped[txn.counterparty_id].append(txn)
    unidentified = total_value - sum(float(t.amount) for items in grouped.values() for t in items)

    overlap: list[str] = []
    in_ledger_period: dict[str, float] = defaultdict(float)
    if ledger and ledger.period_start and ledger.period_end:
        overlap = full_months_between(statements, ledger.period_start, ledger.period_end,
                                      settings["analysis"]["full_month_min_day_share"])
        for txn in all_txns:
            if (txn.category == spec["category"] and txn.counterparty_id
                    and ledger.period_start <= txn.day <= ledger.period_end):
                in_ledger_period[txn.counterparty_id] += float(txn.amount)

    ranked = sorted(grouped.items(), key=lambda item: sum(float(t.amount) for t in item[1]), reverse=True)
    rows = []
    for party_id, items in ranked[:settings["partners"]["top_n"]]:
        value = sum(float(t.amount) for t in items)
        entry = None
        if ledger and kind_of(party_id) == spec["ledger"]:
            entry = ledger.entries[int(party_id.split(":", 1)[1])]
        tax_codes = Counter(t.cp_tax_code for t in items if t.cp_tax_code)
        tax_code = (entry.tax_code if entry and entry.tax_code else
                    tax_codes.most_common(1)[0][0] if tax_codes else "")
        basis = float(getattr(entry, spec["basis"])) if entry else None
        cash_in_period = in_ledger_period.get(party_id, 0.0)
        rows.append({
            "party_id": party_id, "name": entry.name if entry else items[0].counterparty_name,
            "in_ledger": entry is not None,
            "ledger_debit": float(entry.debit) if entry else None,
            "ledger_credit": float(entry.credit) if entry else None,
            "value": value, "share": value / total_value * 100 if total_value else 0.0,
            "cash_in_ledger_period": cash_in_period if entry else None,
            "ratio": cash_in_period / basis * 100 if entry and basis else None,
            "tax_code": tax_code, "count": len(items),
        })
    return {
        "side": side, "ledger_present": ledger is not None,
        "ledger_period": (ledger.period_start, ledger.period_end) if ledger else None,
        "overlap_months": overlap,
        "overlap_limited": len(overlap) < settings["partners"]["min_overlap_months"],
        "rows": rows, "total_value": total_value, "unidentified_value": unidentified,
        "unidentified_share": unidentified / total_value * 100 if total_value else 0.0,
        "matched_share": sum(r["value"] for r in rows if r["in_ledger"]) / total_value * 100
                         if total_value else 0.0,
    }
