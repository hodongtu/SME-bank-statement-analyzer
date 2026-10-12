"""Write one run's outputs: report.md / .pdf, result.json, giao_dich.csv, trace.json."""

from __future__ import annotations

import csv
import dataclasses
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.categories import LABELS
from src.facts import FACT_KEYS

REPORT_CSS = """
@page { size: A4 landscape; margin: 10mm 9mm 12mm 9mm;
        @bottom-center { content: counter(page) " / " counter(pages); font-size: 7.5pt; color: #666; } }
body { font-family: "Times New Roman", Times, "Liberation Serif", serif; font-size: 9pt; line-height: 1.35; }
h1 { font-size: 14pt; margin: 6px 0; } h2 { font-size: 11.5pt; margin: 12px 0 5px; }
h3 { font-size: 10pt; margin: 9px 0 4px; }
table { border-collapse: collapse; width: 100%; margin: 5px 0; font-size: 7.5pt; page-break-inside: auto; }
th, td { border: 1px solid #999; padding: 2px 4px; vertical-align: middle; overflow-wrap: break-word; }
th { background: #eef2f6; }
tr { page-break-inside: avoid; }
"""


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _plain(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def result_json(result) -> dict:
    analysis = result.analysis
    keep = ("customer_name", "coverage", "score", "matrix", "overview", "vat", "partners",
            "balance_checks", "label_sources", "inventory", "revenue_basis", "indicator_notes")
    payload = {key: _plain(analysis.get(key)) for key in keep}
    payload["period"] = _plain(analysis.get("period"))
    payload["tax_code"] = result.state.get("tax_code")
    payload["customer_key"] = result.state.get("customer_key")
    payload["documents"] = [{"file": e.document.filename, "doc_type": e.doc_type, "backend": e.backend,
                             "status": e.status, "reason": e.reason, "warnings": e.warnings,
                             "provenance": _plain(e.provenance)}
                            for e in result.state.get("extracted_documents", [])]
    payload["facts"] = _plain(result.facts.to_dict())
    payload["steps"] = result.steps
    return payload


def trace_json(result) -> dict:
    facts = result.facts
    return {path: {"description": spec.description, "category": spec.category,
                   "present": facts.has(path),
                   "value": _plain(facts.get(path)) if facts.has(path) else None,
                   "missing_reason": facts.missing_reason(path)}
            for path, spec in FACT_KEYS.items()}


def write_transactions(result, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Ngày", "Tài khoản", "Ngân hàng", "Vào/Ra", "Số tiền", "Nội dung", "Tên GD ngân hàng",
                         "Tên đối ứng", "MST đối ứng", "Mã loại", "Loại dòng tiền", "Cách xác định",
                         "Đối tác", "Ghi chú khớp", "File", "Dòng"])
        for t in result.state.get("transactions", []):
            writer.writerow([t.posted_at.strftime("%d/%m/%Y %H:%M"), t.account, t.bank,
                             "Vào" if t.direction == "IN" else "Ra", f"{t.amount:.0f}", t.narrative, t.txn_name,
                             t.cp_name, t.cp_tax_code, t.category, LABELS.get(t.category, ""), t.label_source,
                             t.counterparty_name, t.match_note, t.source_file, t.row_no])


def write_pdf(markdown_text: str, path: Path) -> str:
    """Returns an error message instead of raising: the PDF is a convenience copy."""

    try:
        import markdown
        from weasyprint import HTML
    except Exception as exc:                               # noqa: BLE001
        return f"PDF export failed: {type(exc).__name__}: {exc}"[:300]
    body = markdown.markdown(markdown_text, extensions=["tables"])
    html = f"<html><head><meta charset='utf-8'><style>{REPORT_CSS}</style></head><body>{body}</body></html>"
    HTML(string=html).write_pdf(str(path))
    return ""


def write_outputs(result, out_dir: str | Path, pdf: bool = True) -> dict[str, str]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.md").write_text(result.report_markdown, encoding="utf-8")
    (target / "result.json").write_text(json.dumps(result_json(result), ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "trace.json").write_text(json.dumps(trace_json(result), ensure_ascii=False, indent=2), encoding="utf-8")
    write_transactions(result, target / "classified_transactions.csv")
    written = {name: str(target / name) for name in ("report.md", "result.json", "trace.json",
                                                      "classified_transactions.csv")}
    if pdf:
        error = write_pdf(result.report_markdown, target / "report.pdf")
        written["report.pdf"] = error or str(target / "report.pdf")
    return written
