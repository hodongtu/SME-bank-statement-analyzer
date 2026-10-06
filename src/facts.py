"""The fact sheet: the single boundary between collection and grading."""

from __future__ import annotations

import json
from typing import Any, Iterable, NamedTuple


class _Missing:
    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "<missing>"


MISSING = _Missing()
DEFAULT_MISSING_REASON = "chưa thu thập được"

STATEMENT, LEDGER, TAX, T24, FRAUD, CIC, VIRAC, TRADE, LISTS, REGISTRY = (
    "Sao kê", "Sổ 131/331", "BCTC/VAT", "T24", "Fraud", "CIC", "VIRAC", "XNK", "BL/WL", "ĐKKD")
QUERY, DOSSIER, DERIVED = "query", "dossier", "derived"


class FactSpec(NamedTuple):
    category: str
    delivery: str
    description: str


FACT_KEYS: dict[str, FactSpec] = {
    # BRD 2.1 - data scope and coverage
    "stmt.full_months":            FactSpec(STATEMENT, DERIVED, "Số tháng sao kê đủ trong kỳ yêu cầu"),
    "stmt.missing_months":         FactSpec(STATEMENT, DERIVED, "Các tháng sao kê thiếu hoặc không đủ"),
    "stmt.revenue_coverage_pct":   FactSpec(STATEMENT, DERIVED, "Mức độ bao phủ doanh thu của tiền vào HĐKD, %"),
    "stmt.balance_error_pct":      FactSpec(STATEMENT, DERIVED, "Tỷ lệ giao dịch sai liên tục số dư, %"),
    "stmt.balance_reconciled":     FactSpec(STATEMENT, DERIVED, "Mọi tài khoản đối chiếu được số dư"),
    "fraud.alert_accounts":        FactSpec(FRAUD, QUERY, "Tài khoản có cảnh báo của Fraud"),
    "fraud.unscreened_accounts":   FactSpec(FRAUD, QUERY, "Tài khoản sao kê chưa qua xử lý của Fraud"),
    "t24.accounts_without_statement": FactSpec(T24, QUERY, "Tài khoản tại TCB chưa có sao kê trong hồ sơ"),
    # BRD 2.6 - scoring indicators
    "score.inflow_to_reported_revenue": FactSpec(TAX, DERIVED, "Tỷ lệ tiền vào KD / doanh thu BCTC, %"),
    "score.vat_gap":               FactSpec(TAX, DERIVED, "Chênh lệch tiền vào KD với doanh thu VAT, %"),
    "score.inflow_matched_131":    FactSpec(LEDGER, DERIVED, "Tỷ lệ giá trị tiền thu bán hàng khớp đối tượng sổ 131, %"),
    "score.unclassified_share":    FactSpec(STATEMENT, DERIVED, "Tỷ lệ dòng tiền chưa xác định bản chất, %"),
    "score.reported_vs_third_party":   FactSpec(VIRAC, QUERY, "Chênh lệch doanh thu BCTC với dữ liệu VIRAC, %"),
    "score.trade_industry_legal":    FactSpec(REGISTRY, QUERY, "Mức phù hợp dữ liệu XNK/ngành/pháp lý"),
    # BRD 2.6c - the three data pillars
    "pillar.representative_statement": FactSpec(STATEMENT, DERIVED, "Sao kê đại diện"),
    "pillar.financial_statement":                 FactSpec(TAX, DOSSIER, "BCTC năm gần nhất"),
    "pillar.vat_12m":              FactSpec(TAX, DOSSIER, "Tờ khai VAT 12 tháng"),
}


class UnknownFactError(KeyError):
    """A path nobody declared in FACT_KEYS."""


def _is_empty(value: Any) -> bool:
    if value is None or value is MISSING:
        return True
    if isinstance(value, (str, bytes)):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict, frozenset)):
        return len(value) == 0
    return False


class Facts:
    def __init__(self, values: dict[str, Any] | None = None,
                 reasons: dict[str, str] | None = None) -> None:
        self._values: dict[str, Any] = {}
        self._reasons: dict[str, str] = dict(reasons or {})
        self._empty_notes: dict[str, str] = {}
        for path, value in (values or {}).items():
            self.set(path, value)

    def _check(self, path: str) -> None:
        if path not in FACT_KEYS:
            raise UnknownFactError(f"'{path}' is not declared in FACT_KEYS (src/facts.py)")

    def set(self, path: str, value: Any, *, reason: str = "") -> None:
        """An empty value is recorded as absent, never as a value."""

        self._check(path)
        if _is_empty(value):
            self.mark_missing(path, reason or DEFAULT_MISSING_REASON)
            return
        self._values[path] = value
        self._reasons.pop(path, None)

    def set_empty(self, path: str, note: str) -> None:
        """Record that an empty collection is the answer, not a gap."""

        self._check(path)
        self._values[path] = []
        self._empty_notes[path] = note
        self._reasons.pop(path, None)

    def mark_missing(self, path: str, reason: str) -> None:
        self._check(path)
        self._values.pop(path, None)
        self._reasons[path] = reason or DEFAULT_MISSING_REASON

    def get(self, path: str) -> Any:
        self._check(path)
        return self._values.get(path, MISSING)

    def has(self, path: str) -> bool:
        return self.get(path) is not MISSING

    def missing(self, paths: Iterable[str]) -> list[str]:
        return [path for path in paths if self.get(path) is MISSING]

    def reason(self, path: str) -> str:
        return f"{FACT_KEYS[path].description}: {self._reasons.get(path, DEFAULT_MISSING_REASON)}"

    def missing_reason(self, path: str) -> str:
        return self._reasons.get(path, "")

    def empty_note(self, path: str) -> str:
        return self._empty_notes.get(path, "")

    def to_dict(self) -> dict[str, Any]:
        return {"values": dict(self._values), "reasons": dict(self._reasons)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Facts":
        return cls(payload.get("values"), payload.get("reasons"))

    @classmethod
    def from_json_file(cls, path: str) -> "Facts":
        with open(path, encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def __repr__(self) -> str:
        return f"Facts({len(self._values)}/{len(FACT_KEYS)} collected)"
