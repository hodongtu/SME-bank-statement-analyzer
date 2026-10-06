"""Read one bank statement file into Transaction rows."""

from __future__ import annotations

import re
from pathlib import Path

from src.types import StatementFile, Transaction
from src.utils.common import digits_only, normalize_text
from src.utils.numbers import find_period, parse_amount, parse_datetime
from src.utils.reading.tables import read_rows

HEADER_SCAN_ROWS = 40
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
        debit, credit = parse_amount(cell(row, "debit")), parse_amount(cell(row, "credit"))
        posted = parse_datetime(cell(row, "posted_at"), spec["date_formats"])
        if posted is None:
            label = normalize_text(" ".join(row[:3]))
            if not _TOTAL_LABEL.match(label):
                bad_dates += 1
            continue
        debit, credit = debit or 0, credit or 0
        if (debit > 0) == (credit > 0) or debit < 0 or credit < 0:
            bad_amounts += 1
            continue
        transactions.append(Transaction(
            account=digits_only(cell(row, "account")) or meta.get("account", ""),
            bank=record.bank,
            currency=(cell(row, "currency") or meta.get("currency") or base_currency).upper(),
            posted_at=posted,
            direction="IN" if credit > 0 else "OUT",
            amount=credit if credit > 0 else debit,
            narrative=cell(row, "narrative"),
            entry_id=cell(row, "entry_id"),
            txn_code=cell(row, "txn_code"),
            txn_name=cell(row, "txn_name"),
            txn_type=cell(row, "txn_type"),
            cp_name=cell(row, "cp_name"),
            cp_account=cell(row, "cp_account"),
            cp_tax_code=digits_only(cell(row, "cp_tax_code")),
            cp_bank=cell(row, "cp_bank"),
            balance_after=parse_amount(cell(row, "balance")) if "balance" in columns else None,
            source_file=path.name,
            row_no=offset,
        ))

    if bad_dates:
        record.errors.append(f"{bad_dates} dòng không đọc được ngày giao dịch, đã bỏ qua")
    if bad_amounts:
        record.errors.append(f"{bad_amounts} dòng có số tiền Nợ/Có không hợp lệ, đã bỏ qua")
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
