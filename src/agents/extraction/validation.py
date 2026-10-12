"""Checks applied to every extracted document, whichever backend read it."""

from __future__ import annotations

from decimal import Decimal

from src.agents.extraction.contract import FAILED, OK, PARTIAL, ExtractedDocument
from src.agents.extraction.vat_extraction import identity_error
from src.types import Ledger

TOLERANCE = Decimal(1)


def validate_ledger(ledger: Ledger) -> None:
    if not ledger.entries:
        return
    debit = sum((e.debit for e in ledger.entries), Decimal(0))
    credit = sum((e.credit for e in ledger.entries), Decimal(0))
    if ledger.reported_debit is None:
        ledger.errors.append("Sổ không có dòng Tổng để đối chiếu số đọc được")
        return
    for side, read, printed in (("Nợ", debit, ledger.reported_debit),
                                ("Có", credit, ledger.reported_credit)):
        if abs(read - printed) > TOLERANCE:
            ledger.errors.append(
                f"Tổng phát sinh {side} đọc được {read:,.0f} khác dòng Tổng của sổ {printed:,.0f}")


def validate(extracted: ExtractedDocument) -> ExtractedDocument:
    if extracted.ledger is not None:
        validate_ledger(extracted.ledger)
        if extracted.ledger.errors and extracted.status == OK:
            extracted.status, extracted.reason = PARTIAL, "; ".join(extracted.ledger.errors)

    if extracted.vat is not None and extracted.vat.lines:
        error = identity_error(extracted.vat.lines)
        if error:
            extracted.status, extracted.reason = FAILED, error
            extracted.vat = None

    record = extracted.statement
    opening = getattr(record, "opening_balance", None)
    closing = getattr(record, "closing_balance", None)
    if record is not None and opening is not None and closing is not None:
        net = sum((t.amount if t.direction == "IN" else -t.amount for t in extracted.transactions), Decimal(0))
        gap = Decimal(opening) + net - Decimal(closing)
        if abs(gap) > TOLERANCE:
            record.errors.append(f"Số dư đầu kỳ cộng phát sinh lệch số dư cuối kỳ {gap:,.0f} đồng")
            if extracted.status == OK:
                extracted.status, extracted.reason = PARTIAL, "; ".join(record.errors)
    return extracted
