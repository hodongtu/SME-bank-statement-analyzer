"""Numbers the way the report prints them."""

from __future__ import annotations

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
