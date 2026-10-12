"""Backend for files this project reads itself: CSV, Excel and tax XML."""

from __future__ import annotations

from src.agents.extraction.contract import FAILED, OK, PARTIAL, SKIPPED, ExtractedDocument, not_read
from src.agents.extraction.financial_statement_extraction import read_financial_statement
from src.agents.extraction.ledger_extraction import read_ledger
from src.agents.extraction.statement_extraction import read_statement
from src.agents.extraction.vat_extraction import read_vat
from src.types import CaseDocument
from src.utils.reading.etax_xml import load_filing

NAME = "local"
NOT_READ = "Chưa đọc tự động ở phiên bản này"
SKIP_REASONS = {"cic": "Dữ liệu CIC lấy từ hệ thống, không đọc file"}


class LocalExtractor:
    name = NAME

    def __init__(self, settings: dict) -> None:
        self.settings = settings

    def extract(self, document: CaseDocument) -> ExtractedDocument:
        suffix = document.path.suffix.lower()
        kind = document.doc_type
        if kind == "tax_xml" or suffix == ".xml":
            return self._tax_xml(document)
        if suffix in (".csv", ".xlsx", ".xls", ".xlsm"):
            if kind == "statement":
                return self._statement(document)
            if kind in ("ledger_131", "ledger_331"):
                return self._ledger(document)
            if kind == "vat_return":
                return self._vat(document)
        return not_read(document, NAME, SKIPPED, SKIP_REASONS.get(kind, NOT_READ))

    def _statement(self, document: CaseDocument) -> ExtractedDocument:
        record, rows = read_statement(document.path, self.settings["statement_formats"],
                                      self.settings["analysis"]["base_currency"])
        status = FAILED if not rows else PARTIAL if record.errors else OK
        reason = "; ".join(record.errors) or ("Không có giao dịch nào đọc được" if not rows else "")
        return ExtractedDocument(document=document, doc_type="statement", backend=NAME, status=status,
                                 reason=reason, source_format=document.path.suffix.lower().lstrip("."),
                                 statement=record, transactions=rows)

    def _ledger(self, document: CaseDocument) -> ExtractedDocument:
        ledger = read_ledger(document.path, document.doc_type[-3:])
        status = FAILED if not ledger.entries else PARTIAL if ledger.errors else OK
        return ExtractedDocument(document=document, doc_type=document.doc_type, backend=NAME, status=status,
                                 reason="; ".join(ledger.errors), ledger=ledger,
                                 source_format=document.path.suffix.lower().lstrip("."))

    def _vat(self, document: CaseDocument) -> ExtractedDocument:
        vat, tax_code, name, error = read_vat(document.path)
        return ExtractedDocument(document=document, doc_type="vat_return", backend=NAME,
                                 status=FAILED if error else OK, reason=error, tax_code=tax_code,
                                 taxpayer_name=name, source_format=document.path.suffix.lower().lstrip("."),
                                 vat=vat)

    def _tax_xml(self, document: CaseDocument) -> ExtractedDocument:
        _, header = load_filing(str(document.path))
        if header.kind == "vat":
            return self._vat(document)
        if header.kind == "financial_statement":
            return self._financial_statement(document)
        return ExtractedDocument(document=document, doc_type="tax_xml", backend=NAME, status=FAILED,
                                 reason=header.error or "Không nhận ra loại hồ sơ thuế XML",
                                 tax_code=header.taxpayer_id, taxpayer_name=header.taxpayer_name,
                                 source_format="xml")

    def _financial_statement(self, document: CaseDocument) -> ExtractedDocument:
        summary, tax_code, name, error = read_financial_statement(document.path)
        return ExtractedDocument(document=document, doc_type="financial_statement", backend=NAME,
                                 status=FAILED if error else OK, reason=error, tax_code=tax_code,
                                 taxpayer_name=name, source_format="xml", financials=summary)
