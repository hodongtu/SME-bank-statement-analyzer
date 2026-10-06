"""Decide what each file of a case is."""

from __future__ import annotations

from pathlib import Path

from src.types import CaseDocument
from src.utils.common import normalize_text
from src.utils.reading.tables import read_rows

TABULAR = (".csv", ".xlsx", ".xlsm", ".xls")


def _head_text(path: Path, rows: int = 15) -> str:
    try:
        return normalize_text(" ".join(" ".join(r) for r in read_rows(path)[:rows]))
    except Exception:
        return ""


def identify(document: CaseDocument, document_types: dict) -> str:
    name = document.filename.lower()
    suffix = document.path.suffix.lower()
    if suffix == ".xml":
        return "tax_xml"
    for type_id, spec in document_types.items():
        if any(str(word).lower() in name for word in spec.get("filename") or []):
            return type_id
    if suffix in TABULAR:
        head = _head_text(document.path)
        for type_id, spec in document_types.items():
            if any(f" {word} " in f" {head} " for word in spec.get("content") or []):
                return type_id
    return "other"
