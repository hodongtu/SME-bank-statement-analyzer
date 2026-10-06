"""Every row of a CSV or Excel sheet as strings, untruncated."""

from __future__ import annotations

import csv
from pathlib import Path


def read_csv_rows(path: str | Path) -> list[list[str]]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1258", "latin-1"):
        try:
            with open(path, newline="", encoding=encoding) as handle:
                return [[cell.strip() for cell in row] for row in csv.reader(handle)]
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"cannot decode CSV file: {last_error}")


def read_excel_rows(path: str | Path) -> list[list[str]]:
    """First non-empty sheet; dates and numbers keep their Python value as text."""

    suffix = Path(path).suffix.lower()
    if suffix == ".xls":
        import pandas as pd

        frame = pd.read_excel(path, header=None, dtype=object)
        return [["" if v is None or v != v else str(v).strip() for v in row]
                for row in frame.itertuples(index=False)]

    from openpyxl import load_workbook

    workbook = load_workbook(path, data_only=True, read_only=True)
    for sheet in workbook.worksheets:
        rows = [
            ["" if value is None else (value.isoformat(sep=" ") if hasattr(value, "isoformat")
                                       else str(value)).strip() for value in row]
            for row in sheet.iter_rows(values_only=True)
        ]
        if any(any(cell for cell in row) for row in rows):
            return rows
    return []


def read_rows(path: str | Path) -> list[list[str]]:
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return read_csv_rows(path)
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return read_excel_rows(path)
    raise ValueError(f"unsupported table format {suffix}")
