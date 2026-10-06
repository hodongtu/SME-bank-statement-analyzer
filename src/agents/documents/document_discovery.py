"""Find the files of one case."""

from __future__ import annotations

from pathlib import Path

from src.types import CaseDocument


class CaseLayoutError(RuntimeError):
    """The case folder is not <case>/<box>/<file>."""


def discover(case_dir: str | Path) -> list[CaseDocument]:
    root = Path(case_dir)
    if not root.is_dir():
        raise CaseLayoutError(f"case folder not found: {root}")
    documents: list[CaseDocument] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        depth = len(path.relative_to(root).parts)
        if depth > 2:
            raise CaseLayoutError(
                f"{path.relative_to(root)} is deeper than <case>/<box>/<file>; "
                f"one run handles one case")
        box = path.parent.name if depth == 2 else ""
        documents.append(CaseDocument(path=path, box=box))
    return documents
