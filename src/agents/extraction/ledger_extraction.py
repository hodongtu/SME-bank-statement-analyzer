"""Read a 131 / 331 subsidiary ledger and prove it against its own total row."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from src.types import Ledger, LedgerEntry
from src.utils.common import digits_only, normalize_text
from src.utils.numbers import find_period, parse_amount
from src.utils.reading.tables import read_rows

HEADERS: dict[str, tuple[str, ...]] = {
    "name": ("doi tuong", "ten doi tuong", "ten khach hang", "ten nha cung cap",
             "khach hang", "nha cung cap"),
    "tax_code": ("ma so thue", "mst"),
    "opening_debit": ("du no dau ky", "no dau ky"),
    "opening_credit": ("du co dau ky", "co dau ky"),
    "debit": ("phat sinh no", "ps no"),
    "credit": ("phat sinh co", "ps co"),
    "closing_debit": ("du no cuoi ky", "no cuoi ky"),
    "closing_credit": ("du co cuoi ky", "co cuoi ky"),
}
AMOUNT_FIELDS = ("opening_debit", "opening_credit", "debit", "credit",
                 "closing_debit", "closing_credit")
_TOTAL = re.compile(r"^(tong( cong)?|cong)( phat sinh)?$")
_LEADING_NUMBERS = re.compile(r"^[\s\d.,%()\-]*")


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    for index, row in enumerate(rows[:40]):
        cells = [normalize_text(cell) for cell in row]
        found = {field: cells.index(word) for field, words in HEADERS.items()
                 for word in words if word in cells}
        if {"name", "debit", "credit"} <= set(found):
            return index, found
    return None


def _company_line(rows: list[list[str]]) -> str:
    for row in rows:
        text = " ".join(cell for cell in row if cell.strip()).strip()
        if re.match(r"^(cong ty|cty|doanh nghiep|ho kinh doanh|hkd)\b", normalize_text(text)):
            return text
    return ""


def _split_merged(row: list[str], data_width: int) -> list[list[str]]:
    """One physical CSV line can hold two records when an export lost a newline."""

    pieces: list[list[str]] = []
    current = row
    while True:
        cut = next((i for i in range(data_width, len(current))
                    if re.search(r"[^\W\d_]", current[i])), None)
        if cut is None:
            pieces.append(current)
            return pieces
        pieces.append(current[:cut])
        current = [_LEADING_NUMBERS.sub("", current[cut]).strip()] + current[cut + 1:]


def read_ledger(path: str | Path, account: str) -> Ledger:
    path = Path(path)
    ledger = Ledger(account=account, filename=path.name)
    try:
        rows = read_rows(path)
    except Exception as exc:
        ledger.errors.append(f"Không đọc được file: {exc}")
        return ledger

    located = _find_header(rows)
    if located is None:
        ledger.errors.append("Không nhận ra hàng tiêu đề (Đối tượng / Phát sinh Nợ / Phát sinh Có)")
        return ledger
    header_index, columns = located
    ledger.company = _company_line(rows[:header_index])
    period = find_period(" ".join(" ".join(r) for r in rows[:header_index]))
    if period:
        ledger.period_start, ledger.period_end = period
    else:
        ledger.errors.append("Không đọc được kỳ của sổ (dòng 'Từ ngày … đến ngày …')")
    data_width = max(columns.values()) + 1

    records: list[list[str]] = []
    dangling = ""
    for row in rows[header_index + 1:]:
        pieces = _split_merged(row, data_width)
        if len(pieces) > 1:
            ledger.repaired_rows += 1
        for piece_index, piece in enumerate(pieces):
            if dangling and piece_index == 0 and piece:
                piece = [f"{dangling} {piece[0]}".strip()] + piece[1:]
                dangling = ""
            is_tail = piece_index == len(pieces) - 1 and piece_index > 0
            if is_tail and len(piece) == 1 and piece[0]:
                dangling = piece[0]
                continue
            records.append(piece)

    def cell(record: list[str], field: str) -> str:
        position = columns.get(field)
        return record[position].strip() if position is not None and position < len(record) else ""

    for record in records:
        name = cell(record, "name")
        label = normalize_text(name)
        amounts = {field: parse_amount(cell(record, field)) for field in AMOUNT_FIELDS}
        if _TOTAL.match(label):
            ledger.reported_debit = amounts["debit"] or Decimal(0)
            ledger.reported_credit = amounts["credit"] or Decimal(0)
            continue
        if not label:
            continue
        ledger.entries.append(LedgerEntry(
            name=" ".join(name.split()),
            tax_code=digits_only(cell(record, "tax_code")),
            **{field: value or Decimal(0) for field, value in amounts.items()},
        ))

    if not ledger.entries:
        ledger.errors.append("Sổ không có đối tượng nào")
    return ledger
