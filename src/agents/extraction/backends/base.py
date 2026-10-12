"""The one interface every extraction backend implements."""

from __future__ import annotations

from typing import Protocol

from src.agents.extraction.contract import ExtractedDocument
from src.types import CaseDocument


class DocumentExtractor(Protocol):
    name: str

    def extract(self, document: CaseDocument) -> ExtractedDocument: ...
