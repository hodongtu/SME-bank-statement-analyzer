"""Send each uploaded file to the backend config/extraction.yaml names, and police what comes back."""

from __future__ import annotations

from src.agents.extraction.backends.base import DocumentExtractor
from src.agents.extraction.backends.it_service import ITServiceExtractor
from src.agents.extraction.backends.local import LocalExtractor
from src.agents.extraction.contract import (FAILED, SKIPPED, ExtractedDocument, contract_problems,
                                            not_read)
from src.agents.extraction.validation import validate
from src.types import CaseDocument

BAD_SHAPE = "Kết quả đọc tài liệu không đúng định dạng dữ liệu của hệ thống"
OVER_BUDGET = "Vượt giới hạn số tài liệu gửi dịch vụ đọc tài liệu trong một lần chạy"


class ExtractionRouter:
    def __init__(self, settings: dict, backends: dict[str, DocumentExtractor] | None = None) -> None:
        self.options = settings["extraction"]
        self.backends: dict[str, DocumentExtractor] = {
            "local": LocalExtractor(settings), "it_service": ITServiceExtractor(settings), **(backends or {})}
        self.calls = 0

    def reset(self) -> None:
        self.calls = 0

    def group(self, document: CaseDocument) -> str:
        suffix = document.path.suffix.lower()
        return next((name for name, suffixes in self.options["formats"].items() if suffix in suffixes), "")

    def backend_for(self, document: CaseDocument) -> str:
        name = self.options["routing"].get(self.group(document), "local")
        if name == "it_service" and document.doc_type not in self.options["it_service"]["doc_types"]:
            return "local"
        return name

    def extract(self, document: CaseDocument) -> ExtractedDocument:
        name = self.backend_for(document)
        if name == "it_service":
            if self.calls >= int(self.options["it_service"]["max_calls_per_run"]):
                return not_read(document, name, SKIPPED, OVER_BUDGET)
            self.calls += 1
        extracted = self.backends[name].extract(document)
        problems = contract_problems(extracted)
        if problems:
            return not_read(document, extracted.backend, FAILED, BAD_SHAPE,
                            doc_type=extracted.doc_type, warnings=problems)
        return validate(extracted)
