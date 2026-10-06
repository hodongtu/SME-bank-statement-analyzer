"""Clean the merged transaction list: duplicates, currency, internal transfers."""

from __future__ import annotations

from datetime import timedelta

from src.categories import INTERNAL
from src.types import Transaction

PAIR_SOURCE = "Ghép chuyển nội bộ"


def drop_duplicates(transactions: list[Transaction]) -> tuple[list[Transaction], int]:
    seen: set[tuple] = set()
    kept: list[Transaction] = []
    for txn in transactions:
        key = txn.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        kept.append(txn)
    return kept, len(transactions) - len(kept)


def split_currency(transactions: list[Transaction], base: str
                   ) -> tuple[list[Transaction], list[Transaction]]:
    kept = [t for t in transactions if t.currency == base]
    return kept, [t for t in transactions if t.currency != base]


def pair_internal_transfers(transactions: list[Transaction], own_accounts: set[str],
                            max_days: int = 1) -> int:
    """Mark an outflow and inflow of the same amount between two own accounts."""

    inflows: dict = {}
    for txn in transactions:
        if txn.direction == "IN" and not txn.category:
            inflows.setdefault(txn.amount, []).append(txn)
    pairs = 0
    for out in sorted((t for t in transactions if t.direction == "OUT" and not t.category),
                      key=lambda t: t.posted_at):
        if out.cp_account and out.cp_account not in own_accounts:
            continue
        for candidate in inflows.get(out.amount, []):
            if (candidate.category or candidate.account == out.account
                    or abs(candidate.posted_at - out.posted_at) > timedelta(days=max_days)):
                continue
            for txn, other in ((out, candidate), (candidate, out)):
                txn.category = INTERNAL[txn.direction]
                txn.label_source = PAIR_SOURCE
                txn.counterparty_id = "self"
                txn.match_note = f"ghép với TK {other.account} ngày {other.day:%d/%m/%Y}"
            pairs += 1
            break
    return pairs
