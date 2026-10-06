"""Assign each transaction one BRD 2.3 category, most certain evidence first."""

from __future__ import annotations

from src.categories import INTERNAL, RELATED_PARTY, SALES, SUPPLIER, UNCLASSIFIED
from src.agents.transactions.counterparty import (LEDGER_131, LEDGER_331, LENDER, RELATED, SELF,
                                       kind_of)
from src.types import Transaction
from src.utils.common import normalize_text

CODE_SOURCE = "Mã giao dịch ngân hàng"
PARTY_SOURCE = "Đối tác đã biết"
KEYWORD_SOURCE = "Từ khoá nội dung"
MODEL_SOURCE = "Mô hình phân loại"
UNKNOWN_SOURCE = "Chưa xác định"
SOURCE_ORDER = ("Ghép chuyển nội bộ", CODE_SOURCE, PARTY_SOURCE, KEYWORD_SOURCE,
                MODEL_SOURCE, UNKNOWN_SOURCE)


def _contains(text: str, words: list[str]) -> str:
    padded = f" {text} "
    return next((word for word in words if f" {word} " in padded), "")


def by_code(txn: Transaction, code_rules: list[dict]) -> bool:
    name = normalize_text(txn.txn_name)
    for rule in code_rules:
        if rule["direction"] == txn.direction and _contains(name, rule["names"]):
            txn.category, txn.label_source = rule["category"], CODE_SOURCE
            return True
    return False


def by_party(txn: Transaction) -> bool:
    kind = kind_of(txn.counterparty_id)
    category = {
        SELF: INTERNAL[txn.direction],
        RELATED: RELATED_PARTY[txn.direction],
        LENDER: "IN_03" if txn.direction == "IN" else "OUT_05",
        LEDGER_131: SALES if txn.direction == "IN" else "",
        LEDGER_331: SUPPLIER if txn.direction == "OUT" else "",
    }.get(kind, "")
    if category:
        txn.category, txn.label_source = category, PARTY_SOURCE
    return bool(category)


def by_keyword(txn: Transaction, keyword_rules: list[dict]) -> bool:
    text = normalize_text(f"{txn.narrative} {txn.cp_name}")
    for rule in keyword_rules:
        if rule["direction"] != txn.direction:
            continue
        word = _contains(text, rule["keywords"])
        if word:
            txn.category, txn.label_source = rule["category"], KEYWORD_SOURCE
            txn.match_note = (txn.match_note + "; " if txn.match_note else "") + f"từ khoá “{word}”"
            return True
    return False


def classify(transactions: list[Transaction], settings: dict) -> None:
    rules = settings["classification"]
    for txn in transactions:
        if txn.category:
            continue
        if by_code(txn, rules["code_rules"]) or by_party(txn) or by_keyword(txn, rules["keyword_rules"]):
            continue
        txn.category, txn.label_source = UNCLASSIFIED[txn.direction], UNKNOWN_SOURCE
