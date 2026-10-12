"""Read one bank statement file into Transaction rows."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from src.types import StatementFile, Transaction
from src.utils.common import digits_only, normalize_text
from src.utils.numbers import find_period, parse_amount, parse_datetime
from src.utils.reading.tables import read_rows

HEADER_SCAN_ROWS = 40
BAD_DATE, BAD_AMOUNT, TOTAL_ROW = "bad_date", "bad_amount", "total_row"
_TOTAL_LABEL = re.compile(r"^(tong( cong)?|cong|so du dau ky|so du cuoi ky)( |$)")


def _exact_header(rows: list[list[str]], columns: dict[str, str]) -> tuple[int, dict[str, int]] | None:
    wanted = {field: name.strip().lower() for field, name in columns.items()}
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        cells = [cell.strip().lower() for cell in row]
        found = {field: cells.index(name) for field, name in wanted.items() if name in cells}
        if all(field in found for field in ("debit", "credit", "posted_at")):
            return index, found
    return None


def _synonym_header(rows: list[list[str]], synonyms: dict[str, list[str]],
                    required: list[str]) -> tuple[int, dict[str, int]] | None:
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        cells = [normalize_text(cell) for cell in row]
        found: dict[str, int] = {}
        for field, words in synonyms.items():
            for word in words:
                if word in cells and cells.index(word) not in found.values():
                    found[field] = cells.index(word)
                    break
        if all(field in found for field in required):
            return index, found
    return None


def _metadata(rows: list[list[str]], patterns: dict[str, str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for row in rows:
        text = normalize_text(" ".join(row))
        for field, pattern in (patterns or {}).items():
            match = re.search(pattern, text)
            if match and field not in found:
                found[field] = match.group(1).strip()
    return found


def to_transaction(cell: Callable[[str], str], date_formats: list[str], bank: str, meta: dict[str, str],
                   base_currency: str, has_balance: bool, source_file: str, row_no: int,
                   label_text: str) -> Transaction | str:
    """One statement row as a Transaction, or BAD_DATE / BAD_AMOUNT / TOTAL_ROW."""

    debit, credit = parse_amount(cell("debit")), parse_amount(cell("credit"))
    posted = parse_datetime(cell("posted_at"), date_formats)
    if posted is None:
        return TOTAL_ROW if _TOTAL_LABEL.match(normalize_text(label_text)) else BAD_DATE
    debit, credit = debit or 0, credit or 0
    if (debit > 0) == (credit > 0) or debit < 0 or credit < 0:
        return BAD_AMOUNT
    return Transaction(
        account=digits_only(cell("account")) or meta.get("account", ""),
        bank=bank,
        currency=(cell("currency") or meta.get("currency") or base_currency).upper(),
        posted_at=posted,
        direction="IN" if credit > 0 else "OUT",
        amount=credit if credit > 0 else debit,
        narrative=cell("narrative"),
        entry_id=cell("entry_id"),
        txn_code=cell("txn_code"),
        txn_name=cell("txn_name"),
        txn_type=cell("txn_type"),
        cp_name=cell("cp_name"),
        cp_account=cell("cp_account"),
        cp_tax_code=digits_only(cell("cp_tax_code")),
        cp_bank=cell("cp_bank"),
        balance_after=parse_amount(cell("balance")) if has_balance else None,
        source_file=source_file,
        row_no=row_no,
    )


def row_errors(bad_dates: int, bad_amounts: int) -> list[str]:
    errors = []
    if bad_dates:
        errors.append(f"{bad_dates} dòng không đọc được ngày giao dịch, đã bỏ qua")
    if bad_amounts:
        errors.append(f"{bad_amounts} dòng có số tiền Nợ/Có không hợp lệ, đã bỏ qua")
    return errors


def transactions_from_records(records: list[dict], spec: dict, bank: str, source: str,
                              base_currency: str) -> tuple[list[Transaction], list[str]]:
    """System rows keyed by the column names of a `columns` format, through the same conversion as files."""

    columns = spec["columns"]
    transactions: list[Transaction] = []
    bad_dates = bad_amounts = 0
    for index, record in enumerate(records, start=1):
        def cell(field: str, record: dict = record) -> str:
            value = record.get(columns[field]) if field in columns else None
            return "" if value is None else str(value).strip()

        result = to_transaction(cell, spec["date_formats"], bank, {}, base_currency, "balance" in columns,
                                source, index, cell("narrative"))
        if result == BAD_DATE:
            bad_dates += 1
        elif result == BAD_AMOUNT:
            bad_amounts += 1
        elif isinstance(result, Transaction):
            transactions.append(result)
    return transactions, row_errors(bad_dates, bad_amounts)


def read_statement(path: str | Path, formats: list[dict], base_currency: str
                   ) -> tuple[StatementFile, list[Transaction]]:
    path = Path(path)
    record = StatementFile(filename=path.name, bank="")
    try:
        rows = read_rows(path)
    except Exception as exc:
        record.errors.append(f"Không đọc được file: {exc}")
        return record, []

    chosen = None
    for spec in formats:
        if spec.get("columns"):
            located = _exact_header(rows, spec["columns"])
        else:
            located = _synonym_header(rows, spec["header_synonyms"], spec.get("required") or [])
        if located:
            chosen = (spec, *located)
            break
    if chosen is None:
        record.errors.append("Không nhận ra hàng tiêu đề của sao kê theo các định dạng đã khai báo")
        return record, []

    spec, header_index, columns = chosen
    record.format_id = spec["id"]
    above = rows[:header_index]
    meta = _metadata(above, spec.get("metadata_patterns") or {})
    record.bank = spec.get("bank") or meta.get("bank", "").upper() or "Không rõ"
    period = find_period(" ".join(" ".join(row) for row in above))
    if period:
        record.period_start, record.period_end = period
        record.period_declared = True

    def cell(row: list[str], field: str) -> str:
        position = columns.get(field)
        return row[position].strip() if position is not None and position < len(row) else ""

    transactions: list[Transaction] = []
    bad_dates = bad_amounts = 0
    for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(c.strip() for c in row):
            continue
        result = to_transaction(lambda field, row=row: cell(row, field), spec["date_formats"], record.bank, meta,
                                base_currency, "balance" in columns, path.name, offset, " ".join(row[:3]))
        if result == BAD_DATE:
            bad_dates += 1
        elif result == BAD_AMOUNT:
            bad_amounts += 1
        elif isinstance(result, Transaction):
            transactions.append(result)

    record.errors.extend(row_errors(bad_dates, bad_amounts))
    if not transactions:
        record.errors.append("Không có giao dịch nào đọc được")
        return record, []
    if not all(t.account for t in transactions):
        record.errors.append("Có giao dịch không xác định được số tài khoản")
    record.row_count = len(transactions)
    record.accounts = sorted({t.account for t in transactions})
    record.currencies = sorted({t.currency for t in transactions})
    record.has_balance = any(t.balance_after is not None for t in transactions)
    if not record.period_declared:
        record.period_start = min(t.day for t in transactions)
        record.period_end = max(t.day for t in transactions)
    return record, transactions
