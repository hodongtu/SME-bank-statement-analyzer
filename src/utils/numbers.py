"""Amounts and dates as Vietnamese bank and accounting files write them."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_DASH_ONLY = re.compile(r"^[\s\-–—]*$")
_CURRENCY = re.compile(r"(vnđ|vnd|đồng|đ)\s*$", re.IGNORECASE)


def parse_amount(text: object) -> Decimal | None:
    """'1,639,755,000', '1.210.969.204,91', '(500)', ' -  ' -> Decimal; '' -> None."""

    if text is None:
        return None
    if isinstance(text, (int, float, Decimal)):
        return Decimal(str(text))
    raw = str(text).strip()
    if not raw:
        return None
    if _DASH_ONLY.match(raw):
        return Decimal(0)
    raw = _CURRENCY.sub("", raw).strip().replace(" ", "")
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()")
    if raw.startswith("-"):
        negative, raw = True, raw[1:]
    if not re.fullmatch(r"[\d.,]+", raw):
        return None
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif raw.count(",") > 1 or raw.count(".") > 1:
        raw = raw.replace(",", "").replace(".", "")
    elif "," in raw:
        head, tail = raw.split(",")
        raw = head + tail if len(tail) == 3 else head + "." + tail
    elif "." in raw:
        head, tail = raw.split(".")
        raw = head + tail if len(tail) == 3 else raw
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_datetime(text: object, formats: list[str]) -> datetime | None:
    if isinstance(text, datetime):
        return text
    if isinstance(text, date):
        return datetime(text.year, text.month, text.day)
    raw = str(text or "").strip()
    if not raw:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


_VN_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def find_period(text: str) -> tuple[date, date] | None:
    """The first two dd/mm/yyyy dates in a period line -> (start, end)."""

    found = _VN_DATE.findall(text or "")
    if len(found) < 2:
        return None
    try:
        start, end = (date(int(y), int(m), int(d)) for d, m, y in found[:2])
    except ValueError:
        return None
    return (start, end) if start <= end else None


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def shift_month(key: str, offset: int) -> str:
    year, month = (int(part) for part in key.split("-"))
    index = year * 12 + (month - 1) + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_label(key: str) -> str:
    year, month = key.split("-")
    return f"{month}/{year}"
