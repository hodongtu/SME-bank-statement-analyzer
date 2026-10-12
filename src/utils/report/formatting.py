"""Numbers the way the report prints them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

VND_PER_BILLION = 1_000_000_000
NOT_APPLICABLE = "—"


def format_vn_number(value: float, decimals: int = 2) -> str:
    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def bn(value: float | None, decimals: int = 2) -> str:
    """VND -> billions; zero prints as '-', no value as '—'."""

    if value is None:
        return NOT_APPLICABLE
    if abs(value) < 0.5 * 10 ** (9 - decimals):
        return "-"
    return format_vn_number(value / VND_PER_BILLION, decimals)


def pct(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return NOT_APPLICABLE
    return format_vn_number(value, decimals) + "%"


def money(value: float | None) -> str:
    if value is None:
        return NOT_APPLICABLE
    return format_vn_number(value, 0) + " đ"


def table(headers: list[str], rows: list[list[str]], align: str = "") -> str:
    """Markdown table; align is one letter per column (l/r/c), default left."""

    marks = {"l": "---", "r": "---:", "c": ":---:"}
    rule = [marks.get(align[i] if i < len(align) else "l") for i in range(len(headers))]
    clean = lambda cell: str(cell).replace("|", "/").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(rule) + "|"]
    lines += ["| " + " | ".join(clean(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def bold(text: str) -> str:
    return f"**{text}**" if text else ""


def decimal_comma(value: float, decimals: int = 1) -> str:
    return format(value, f".{decimals}f").replace(".", ",")


@dataclass(frozen=True)
class Col:
    """One table column: header, how to print a row's cell, alignment (l/r/c), optional total-row cell (text or function)."""

    header: str
    value: Callable[[Any], str] | None = None
    align: str = "l"
    total: Callable[[list], str] | str | None = None


NUMBER = Col("STT", None, "c")


def build_table(columns: list[Col], items: Iterable, empty: str = "") -> str:
    """Markdown table from column definitions; a column whose value is None prints the row number."""

    items = list(items)
    if not items and empty:
        return empty
    rows = [[str(number) if col.value is None else col.value(item) for col in columns]
            for number, item in enumerate(items, start=1)]
    if any(col.total for col in columns):
        rows.append([col.total if isinstance(col.total, str) else col.total(items) if col.total else ""
                     for col in columns])
    return table([col.header for col in columns], rows, "".join(col.align for col in columns))
