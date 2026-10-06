"""BRD 2.6 - revenue reliability: the six indicators, the three pillars, the rating."""

from __future__ import annotations

from datetime import date

from src.agents.calculator.period import Period, full_months_between, monthly_sum
from src.agents.transactions.counterparty import LEDGER_131, kind_of
from src.facts import FACT_KEYS, Facts
from src.types import StatementFile, Transaction

INDICATOR_FACTS = {
    "inflow_to_reported_revenue": "score.inflow_to_reported_revenue",
    "vat_gap": "score.vat_gap",
    "inflow_matched_131": "score.inflow_matched_131",
    "unclassified_share": "score.unclassified_share",
    "reported_vs_third_party": "score.reported_vs_third_party",
    "trade_industry_legal": "score.trade_industry_legal",
}
PILLARS = ("pillar.representative_statement", "pillar.financial_statement", "pillar.vat_12m")
Measured = tuple[float | str | None, str]


def inflow_to_reported_revenue(all_txns: list[Transaction], statements: list[StatementFile],
                   reported_revenue: dict[int, float], settings: dict) -> Measured:
    if not reported_revenue:
        return None, "không có BCTC đọc được"
    year = max(reported_revenue)
    months = full_months_between(statements, date(year, 1, 1), date(year, 12, 31),
                                 settings["analysis"]["full_month_min_day_share"])
    if len(months) < settings["analysis"]["min_overlap_months_financials"]:
        return None, (f"sao kê chỉ đủ {len(months)} tháng trong năm {year} của BCTC, "
                      f"cần tối thiểu {settings['analysis']['min_overlap_months_financials']} tháng")
    if reported_revenue[year] <= 0:
        return None, f"doanh thu BCTC năm {year} bằng 0"
    business = monthly_sum(all_txns, set(settings["business_inflow_codes"]), "IN")
    inflow = sum(business.get(m, 0.0) for m in months)
    reference = reported_revenue[year] * len(months) / 12
    return inflow / reference * 100, f"{len(months)} tháng của năm {year}, doanh thu BCTC phân bổ theo tháng"


def vat_gap(window_txns: list[Transaction], period: Period, vat_out: dict[str, tuple],
            settings: dict) -> Measured:
    months = [m for m in period.required if m in period.full and m in vat_out]
    if not months:
        return None, "không có tháng nào vừa đủ sao kê vừa có tờ khai VAT"
    reference = sum(vat_out[m][0] for m in months)
    if reference <= 0:
        return None, "doanh thu VAT các tháng so sánh bằng 0"
    business = monthly_sum(window_txns, set(settings["business_inflow_codes"]), "IN")
    inflow = sum(business.get(m, 0.0) for m in months)
    return abs(inflow - reference) / reference * 100, f"so sánh trên {len(months)} tháng"


def matched_131(window_txns: list[Transaction], has_ledger: bool) -> Measured:
    if not has_ledger:
        return None, "không có sổ chi tiết 131"
    sales = [t for t in window_txns if t.category == "IN_01"]
    total = sum(float(t.amount) for t in sales)
    if total <= 0:
        return None, "không có tiền thu bán hàng trong kỳ"
    matched = sum(float(t.amount) for t in sales if kind_of(t.counterparty_id) == LEDGER_131)
    return matched / total * 100, ""


def unclassified_share(window_txns: list[Transaction]) -> Measured:
    total = sum(float(t.amount) for t in window_txns)
    if total <= 0:
        return None, "không có giao dịch trong kỳ"
    unknown = sum(float(t.amount) for t in window_txns if t.category in ("IN_10", "OUT_11"))
    return unknown / total * 100, "tính trên tổng tiền vào và tiền ra"


def reported_vs_third_party(reported_revenue: dict[int, float], virac: dict | None) -> Measured:
    if not reported_revenue:
        return None, "không có BCTC đọc được"
    if virac is None:
        return None, "chưa tra cứu được VIRAC"
    year = max(reported_revenue)
    third = (virac.get(str(year)) or {}).get("revenue")
    if not third:
        return None, f"VIRAC không có doanh thu năm {year}"
    return abs(reported_revenue[year] - third) / third * 100, f"năm {year}"


def trade_industry_legal(registry: dict | None, blwl_hits: list | None, trade: dict | None,
                       yearly_flows: float, override: str = "") -> Measured:
    if override:
        return override, "theo đánh giá của cán bộ"
    if registry is None or blwl_hits is None:
        return None, "chưa tra cứu được ĐKKD hoặc BL/WL"
    status = str(registry.get("status") or "")
    lists = {str(hit.get("list_type", "")).upper() for hit in blwl_hits}
    if "đang hoạt động" not in status.lower() or "BL" in lists:
        return "Không phù hợp đáng kể", f"trạng thái pháp lý “{status}”" + (", có trong BL" if "BL" in lists else "")
    turnover = 0.0
    if trade:
        latest = trade[max(trade)]
        turnover = float(latest.get("export_value") or 0) + float(latest.get("import_value") or 0)
    if turnover and yearly_flows and turnover > 1.5 * yearly_flows:
        return "Không phù hợp đáng kể", "kim ngạch XNK vượt xa dòng tiền qua tài khoản"
    if "WL" in lists or (turnover and yearly_flows and turnover > yearly_flows):
        return "Có chênh lệch giải thích được", "có trong WL" if "WL" in lists else "kim ngạch XNK lớn hơn dòng tiền"
    return "Phù hợp", "pháp lý đang hoạt động, không có trong BL/WL" + (", XNK tương xứng dòng tiền" if turnover else "")


def points_for(value: float | str, spec: dict) -> int:
    if "levels" in spec:
        return int(spec["levels"][value])
    for band in spec["bands"]:
        if ("from" not in band or value >= band["from"]) and ("to" not in band or value <= band["to"]):
            return int(band["points"])
    return int(spec["otherwise"])


def grade(facts: Facts, settings: dict) -> dict:
    scoring = settings["scoring"]
    indicators, total = [], 0.0
    for key, spec in scoring["indicators"].items():
        path = INDICATOR_FACTS[key]
        if facts.has(path):
            value = facts.get(path)
            points = points_for(value, spec)
            reason = ""
        else:
            value, points, reason = None, int(scoring["missing_points"]), facts.missing_reason(path)
        weighted = spec["weight"] * points / 100
        total += weighted
        indicators.append({"key": key, "label": spec["label"], "weight": spec["weight"],
                           "value": value, "points": points, "weighted": weighted,
                           "missing_reason": reason})
    pillars = [{"label": FACT_KEYS[path].description, "present": bool(facts.get(path)),
                "reason": facts.missing_reason(path)} for path in PILLARS]
    if all(p["present"] for p in pillars):
        band = next(r for r in scoring["rating"] if total >= r["min"])
        rating, usage = band["label"], band["usage"]
    else:
        rating, usage = scoring["insufficient"]["label"], scoring["insufficient"]["usage"]
    return {"indicators": indicators, "total": total, "rating": rating, "usage": usage,
            "pillars": pillars, "computable": all(p["present"] for p in pillars)}
