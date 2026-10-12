"""The shape every extraction backend must return; nothing past this boundary sees a backend's own format."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.types import CaseDocument, Ledger, StatementFile, Transaction

OK, PARTIAL, FAILED, SKIPPED = "ok", "partial", "failed", "skipped"
STATUSES = (OK, PARTIAL, FAILED, SKIPPED)
PAYLOAD_BY_TYPE = {
    "statement": "statement",
    "ledger_131": "ledger",
    "ledger_331": "ledger",
    "vat_return": "vat",
    "financial_statement": "financials",
}


@dataclass
class VatReturn:
    filename: str
    source_format: str
    tax_code: str = ""
    taxpayer_name: str = ""
    period_label: str = "—"
    revenue: dict[str, tuple[float, bool]] = field(default_factory=dict)
    purchases: dict[str, tuple[float, bool]] = field(default_factory=dict)
    lines: dict[str, float] = field(default_factory=dict)


@dataclass
class FinancialStatementSummary:
    filename: str
    source_format: str
    tax_code: str = ""
    taxpayer_name: str = ""
    period_label: str = "—"
    revenue_by_year: dict[int, float] = field(default_factory=dict)
    line_count: int = 0


@dataclass
class ExtractedDocument:
    document: CaseDocument
    doc_type: str
    backend: str
    status: str
    reason: str = ""
    tax_code: str = ""
    taxpayer_name: str = ""
    source_format: str = ""
    warnings: list[str] = field(default_factory=list)
    statement: StatementFile | None = None
    transactions: list[Transaction] = field(default_factory=list)
    ledger: Ledger | None = None
    vat: VatReturn | None = None
    financials: FinancialStatementSummary | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def payloads(self) -> dict[str, Any]:
        return {name: value for name, value in (("statement", self.statement), ("ledger", self.ledger),
                                                ("vat", self.vat), ("financials", self.financials))
                if value is not None}


def _month_key(key: str) -> bool:
    return len(key) == 7 and key[4] == "-" and key[:4].isdigit() and key[5:].isdigit()


def contract_problems(extracted: ExtractedDocument) -> list[str]:
    """Every way an ExtractedDocument breaks the contract. Empty means it may cross the boundary."""

    problems: list[str] = []
    if extracted.status not in STATUSES:
        return [f"status {extracted.status!r} is not one of {STATUSES}"]
    if extracted.status != OK and not extracted.reason.strip():
        problems.append(f"status {extracted.status} carries no reason")
    payloads = extracted.payloads()
    if len(payloads) > 1:
        problems.append(f"more than one payload: {sorted(payloads)}")
    if extracted.status in (OK, PARTIAL):
        expected = PAYLOAD_BY_TYPE.get(extracted.doc_type)
        if expected is None:
            problems.append(f"doc_type {extracted.doc_type!r} has no payload type")
        elif expected not in payloads:
            problems.append(f"doc_type {extracted.doc_type} needs a {expected} payload")
    if extracted.status == SKIPPED and payloads:
        problems.append("a skipped document must carry no payload")

    if extracted.statement is not None:
        if not extracted.statement.filename:
            problems.append("statement without filename")
        for index, txn in enumerate(extracted.transactions):
            where = f"transaction {index}"
            if not isinstance(txn.amount, Decimal) or txn.amount <= 0:
                problems.append(f"{where}: amount must be a positive Decimal")
            if not isinstance(txn.posted_at, datetime):
                problems.append(f"{where}: posted_at must be a datetime")
            if txn.direction not in ("IN", "OUT"):
                problems.append(f"{where}: direction must be IN or OUT")
            if not txn.account:
                problems.append(f"{where}: account is empty")
            if not txn.currency:
                problems.append(f"{where}: currency is empty")
            if len(problems) > 20:
                break
    elif extracted.transactions:
        problems.append("transactions without a statement")

    if extracted.ledger is not None:
        ledger = extracted.ledger
        for value in (ledger.period_start, ledger.period_end):
            if value is not None and not isinstance(value, date):
                problems.append("ledger period must be dates")
        for entry in ledger.entries:
            if not entry.name.strip():
                problems.append("ledger entry without name")
            amounts = (entry.opening_debit, entry.opening_credit, entry.debit, entry.credit,
                       entry.closing_debit, entry.closing_credit)
            if not all(isinstance(a, Decimal) for a in amounts):
                problems.append(f"ledger entry {entry.name!r}: amounts must be Decimal")

    for name, vat_series in (("revenue", getattr(extracted.vat, "revenue", {})),
                             ("purchases", getattr(extracted.vat, "purchases", {}))):
        for key, value in vat_series.items():
            if not _month_key(key) or not (isinstance(value, tuple) and len(value) == 2
                                           and isinstance(value[1], bool)):
                problems.append(f"vat {name}[{key!r}] must be 'YYYY-MM': (amount, is_estimated)")
    if extracted.vat is not None and extracted.status in (OK, PARTIAL) and not extracted.vat.revenue:
        problems.append("vat payload without revenue")

    if extracted.financials is not None:
        for year, value in extracted.financials.revenue_by_year.items():
            if not isinstance(year, int) or not isinstance(value, (int, float)):
                problems.append("financials revenue_by_year must map int year to number")
    return problems


def not_read(document: CaseDocument, backend: str, status: str, reason: str,
             doc_type: str = "", warnings: list[str] | None = None) -> ExtractedDocument:
    return ExtractedDocument(document=document, doc_type=doc_type or document.doc_type, backend=backend,
                             status=status, reason=reason, warnings=list(warnings or []))
