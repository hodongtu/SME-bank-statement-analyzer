"""Every VAT return 01/GTGT, whatever its format, becomes a VatReturn here and only here.

- XML (HTKK/eTax): read_vat_xml.
- Excel exported by HTKK (indicator codes in brackets, amounts beside them): read_vat_excel.
- PDF/images are read by the IT document service; its adapter maps the service's lines onto
  build_vat_return so a PDF return is shaped and checked exactly like the other two.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.agents.extraction.contract import VatReturn
from src.utils.common import digits_only, normalize_text
from src.utils.numbers import parse_amount
from src.utils.reading.tables import read_rows
from src.utils.reading.etax_xml import (FORM_VAT_01GTGT, filing_period, indicator_codes, load_filing, main_block,
                                        year_of)

VAT_CODES = {"23", "24", "26", "27", "28", "29", "30", "31", "32", "32a", "33", "34", "35"}
VAT_PARTS = ("ct26", "ct27", "ct32a")
EXCEL_FORMATS = (".xlsx", ".xls", ".xlsm")
NO_PERIOD = "Không đọc được kỳ kê khai"
_CODE_CELL = re.compile(r"^\[(\w+)\]")
_MONTH = re.compile(r"\bthang (\d{1,2}) nam (\d{4})\b")
_QUARTER = re.compile(r"\bquy (\d) nam (\d{4})\b")

VatRead = tuple[VatReturn | None, str, str, str]          # (return, tax code, taxpayer name, error)


def identity_error(lines: dict[str, float]) -> str:
    """The form defines ct34 = ct26 + ct27 + ct32a; a mismatch means a line was misread."""

    if "ct34" not in lines:
        return ""
    parts = sum(float(lines.get(code, 0.0)) for code in VAT_PARTS)
    if abs(parts - float(lines["ct34"])) > 1:
        return (f"ct34 ({lines['ct34']:,.0f}) khác ct26+ct27+ct32a ({parts:,.0f}) — "
                "không chắc đọc đúng chỉ tiêu.")
    return ""


def build_vat_return(filename: str, source_format: str, tax_code: str, name: str, period_type: str,
                     period_number: int, year: int, lines: dict[str, float]) -> tuple[VatReturn | None, str]:
    """Lines of one return -> monthly series; a quarterly return is split evenly and flagged as estimated."""

    if "ct34" not in lines:
        return None, "Tờ khai không có chỉ tiêu [34] (tổng doanh thu)"
    if period_type == "M":
        keys, estimated = [f"{year:04d}-{period_number:02d}"], False
    elif period_type == "Q":
        keys = [f"{year:04d}-{m:02d}" for m in range(period_number * 3 - 2, period_number * 3 + 1)]
        estimated = True
    else:
        return None, f"Không nhận ra loại kỳ kê khai {period_type!r}"
    share = len(keys)
    return VatReturn(
        filename=filename, source_format=source_format, tax_code=tax_code, taxpayer_name=name,
        period_label=", ".join(sorted(f"{k[5:]}/{k[:4]}" for k in keys)),
        revenue={k: (lines["ct34"] / share, estimated) for k in keys},
        purchases={k: (lines["ct23"] / share, estimated) for k in keys} if "ct23" in lines else {},
        lines=lines,
    ), ""


def read_vat_xml(path: str | Path) -> VatRead:
    path = Path(path)
    root, header = load_filing(str(path))
    if root is None:
        return None, "", "", header.error
    if header.form_id != FORM_VAT_01GTGT:
        return None, header.taxpayer_id, header.taxpayer_name, "Không phải tờ khai thuế GTGT (01/GTGT)"
    period_type, label, end_date = filing_period(root)
    year = year_of(end_date).replace("Năm ", "")
    number = label.split("/")[0].strip()
    if not year or not number.isdigit():
        return None, header.taxpayer_id, header.taxpayer_name, NO_PERIOD
    vat, error = build_vat_return(path.name, "xml", header.taxpayer_id, header.taxpayer_name, period_type,
                                  int(number), int(year), indicator_codes(main_block(root)))
    return vat, header.taxpayer_id, header.taxpayer_name, error


def _excel_lines(rows: list[list[str]]) -> dict[str, float]:
    lines: dict[str, float] = {}
    for row in rows:
        for index, cell in enumerate(row):
            match = _CODE_CELL.match(cell.strip())
            if not match or match.group(1).lower() not in VAT_CODES:
                continue
            for value in row[index + 1:]:
                if _CODE_CELL.match(value.strip()):
                    break
                amount = parse_amount(value)
                if amount is not None:
                    lines[f"ct{match.group(1).lower()}"] = float(amount)
                    break
    return lines


def _labelled_value(rows: list[list[str]], label: str) -> str:
    for row in rows:
        for index, cell in enumerate(row):
            if label in normalize_text(cell):
                after = cell.split(":", 1)[1].strip() if ":" in cell else ""
                if after:
                    return after
                return next((v.strip() for v in row[index + 1:] if v.strip()), "")
    return ""


def read_vat_excel(path: str | Path) -> VatRead:
    path = Path(path)
    try:
        rows = read_rows(path)
    except Exception as exc:
        return None, "", "", f"Không đọc được file: {exc}"
    tax_code = digits_only(_labelled_value(rows, "ma so thue"))
    name = _labelled_value(rows, "ten nguoi nop thue")
    text = " ".join(normalize_text(" ".join(row)) for row in rows)
    month, quarter = _MONTH.search(text), _QUARTER.search(text)
    if month:
        period_type, number, year = "M", int(month.group(1)), int(month.group(2))
    elif quarter:
        period_type, number, year = "Q", int(quarter.group(1)), int(quarter.group(2))
    else:
        return None, tax_code, name, NO_PERIOD
    vat, error = build_vat_return(path.name, path.suffix.lower().lstrip("."), tax_code, name, period_type,
                                  number, year, _excel_lines(rows))
    return vat, tax_code, name, error


def read_vat(path: str | Path) -> VatRead:
    """Entry point for every VAT return this project reads itself (XML and Excel)."""

    suffix = Path(path).suffix.lower()
    if suffix == ".xml":
        return read_vat_xml(path)
    if suffix in EXCEL_FORMATS:
        return read_vat_excel(path)
    return None, "", "", f"Định dạng {suffix} của tờ khai VAT do dịch vụ đọc tài liệu xử lý"
