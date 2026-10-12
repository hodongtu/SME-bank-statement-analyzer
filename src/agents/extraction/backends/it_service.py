"""Backend for the IT document service (PDF and images). Go-live work lives here and nowhere else.

To go live: implement `call` and `to_contract` per the IT spec, then set routing.ocr: it_service
in config/extraction.yaml and fill IT_EXTRACTION_URL / IT_EXTRACTION_TOKEN.
"""

from __future__ import annotations

import os
from typing import Any

from src.agents.extraction.contract import FAILED, SKIPPED, ExtractedDocument, not_read
from src.types import CaseDocument

NAME = "it_service"


class ITServiceExtractor:
    name = NAME

    def __init__(self, settings: dict) -> None:
        options = settings["extraction"]["it_service"]
        self.base_url = os.getenv(options["base_url_env"], "")
        self.token = os.getenv(options["token_env"], "")
        self.timeout = float(options["timeout_seconds"])

    def extract(self, document: CaseDocument) -> ExtractedDocument:
        if not self.base_url:
            return not_read(document, NAME, SKIPPED, "Dịch vụ đọc tài liệu của IT chưa được cấu hình")
        try:
            response = self.call(document)
        except NotImplementedError:
            return not_read(document, NAME, SKIPPED, "Chưa có bộ ánh xạ theo đặc tả của dịch vụ đọc tài liệu IT")
        except Exception as exc:                           # noqa: BLE001 - the reason must reach the report
            return not_read(document, NAME, FAILED, f"Dịch vụ đọc tài liệu IT lỗi: {type(exc).__name__}: {exc}"[:200])
        try:
            return self.to_contract(document, response)
        except NotImplementedError:
            return not_read(document, NAME, SKIPPED, "Chưa có bộ ánh xạ theo đặc tả của dịch vụ đọc tài liệu IT")
        except Exception as exc:                           # noqa: BLE001
            return not_read(document, NAME, FAILED,
                            f"Không chuyển được kết quả của dịch vụ IT: {type(exc).__name__}: {exc}"[:200])

    def call(self, document: CaseDocument) -> dict[str, Any]:
        """Send one file to the IT service and return its JSON response, per the IT spec."""

        raise NotImplementedError

    def to_contract(self, document: CaseDocument, response: dict[str, Any]) -> ExtractedDocument:
        """Map the IT JSON for document.doc_type onto ExtractedDocument (statement, vat or financials).

        A VAT return must go through vat_extraction.build_vat_return so it is shaped like XML/Excel ones.
        """

        raise NotImplementedError
