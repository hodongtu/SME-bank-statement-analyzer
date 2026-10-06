"""The analysis window (T-12 ... T) and which of its months the statements cover."""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.types import StatementFile, Transaction
from src.utils.numbers import month_key, shift_month


@dataclass
class Period:
    current: str
    window: list[str]
    required: list[str]
    coverage: dict[str, float]
    full: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        return [m for m in self.required if m not in self.full]


def covered_days(statements: list[StatementFile]) -> set[date]:
    days: set[date] = set()
    for record in statements:
        if record.period_start and record.period_end and record.row_count:
            day = record.period_start
            while day <= record.period_end:
                days.add(day)
                day += timedelta(days=1)
    return days


def build_period(statements: list[StatementFile], transactions: list[Transaction],
                 analysis_month: str, settings: dict) -> Period:
    rules = settings["analysis"]
    current = analysis_month or (month_key(max(t.day for t in transactions)) if transactions else "")
    if not current:
        return Period(current="", window=[], required=[], coverage={})
    window = [shift_month(current, -i) for i in range(rules["window_months"] - 1, -1, -1)]
    required = window[-rules["required_months"]:]
    days = covered_days(statements)
    coverage: dict[str, float] = {}
    for key in window:
        year, month = (int(p) for p in key.split("-"))
        length = calendar.monthrange(year, month)[1]
        coverage[key] = sum(1 for d in range(1, length + 1) if date(year, month, d) in days) / length
    full = [m for m in window if coverage[m] >= rules["full_month_min_day_share"]]
    return Period(current=current, window=window, required=required, coverage=coverage, full=full)


def in_window(transactions: list[Transaction], period: Period) -> list[Transaction]:
    months = set(period.window)
    return [t for t in transactions if month_key(t.day) in months]


def monthly_sum(transactions: list[Transaction], codes: set[str] | None = None,
                direction: str | None = None) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for txn in transactions:
        if (codes is None or txn.category in codes) and (direction is None or txn.direction == direction):
            totals[month_key(txn.day)] += float(txn.amount)
    return totals


def full_months_between(statements: list[StatementFile], start: date, end: date,
                        min_share: float) -> list[str]:
    days = covered_days(statements)
    months: list[str] = []
    key = month_key(start)
    while key <= month_key(end):
        year, month = (int(p) for p in key.split("-"))
        length = calendar.monthrange(year, month)[1]
        inside = [date(year, month, d) for d in range(1, length + 1) if start <= date(year, month, d) <= end]
        if inside and sum(1 for d in inside if d in days) / length >= min_share:
            months.append(key)
        key = shift_month(key, 1)
    return months
