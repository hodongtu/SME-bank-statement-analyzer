"""Records passed between the reading, classifying and analysing steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict


@dataclass
class CaseDocument:
    path: Path
    box: str
    doc_type: str = ""
    note: str = ""

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass
class Transaction:
    account: str
    bank: str
    currency: str
    posted_at: datetime
    direction: str
    amount: Decimal
    narrative: str = ""
    entry_id: str = ""
    txn_code: str = ""
    txn_name: str = ""
    txn_type: str = ""
    cp_name: str = ""
    cp_account: str = ""
    cp_tax_code: str = ""
    cp_bank: str = ""
    balance_after: Decimal | None = None
    source_file: str = ""
    row_no: int = 0
    category: str = ""
    label_source: str = ""
    counterparty_id: str = ""
    counterparty_name: str = ""
    match_note: str = ""

    @property
    def day(self) -> date:
        return self.posted_at.date()

    def dedupe_key(self) -> tuple:
        return (self.account, self.entry_id, self.posted_at, self.direction,
                self.amount, self.txn_code, self.narrative)


@dataclass
class StatementFile:
    filename: str
    bank: str
    accounts: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None
    period_declared: bool = False
    row_count: int = 0
    has_balance: bool = False
    format_id: str = ""
    errors: list[str] = field(default_factory=list)
    source: str = "file"
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None


@dataclass
class LedgerEntry:
    name: str
    tax_code: str = ""
    opening_debit: Decimal = Decimal(0)
    opening_credit: Decimal = Decimal(0)
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)
    closing_debit: Decimal = Decimal(0)
    closing_credit: Decimal = Decimal(0)


@dataclass
class Ledger:
    account: str
    filename: str
    company: str = ""
    period_start: date | None = None
    period_end: date | None = None
    entries: list[LedgerEntry] = field(default_factory=list)
    reported_debit: Decimal | None = None
    reported_credit: Decimal | None = None
    errors: list[str] = field(default_factory=list)
    repaired_rows: int = 0


class AnalyzerState(TypedDict, total=False):
    case_dir: str
    tax_code: str
    customer_key: dict[str, Any]
    analysis_month: str
    report_date: str
    documents: list[CaseDocument]
    statements: list[StatementFile]
    transactions: list[Transaction]
    ledgers: dict[str, Ledger]
    extracted_documents: list[Any]
    tax_filings: dict[str, Any]
    reference: dict[str, Any]
    facts: Any
    analysis: dict[str, Any]
    report_markdown: str
    steps: list[str]
