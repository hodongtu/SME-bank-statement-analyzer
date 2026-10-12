"""Fill the report template from the analysis. Every word here is fixed Vietnamese text.

How to edit:
- Each table is a list of Col(header, value, align, total): one line per column.
  Rename a header, reorder, add or remove a column by editing that one line.
  value: how to print one row's cell. align: "l" left, "r" right, "c" centre.
  total: optional cell of the total row at the bottom: a text, or a function of all rows.
- NUMBER is the running row number (STT).
- Sections follow src/templates/cashflow-report.md; PLACEHOLDERS at the bottom says which
  function fills which {{placeholder}}.
"""

from __future__ import annotations

from datetime import date

from src.facts import FACT_KEYS
from src.utils.numbers import month_label
from src.utils.report.formatting import (NOT_APPLICABLE, NUMBER, Col, bn, bold, build_table, decimal_comma,
                                         money, pct)
from src.utils.report.templates import get_template

DIRECTION = {"IN": "Vào", "OUT": "Ra"}
NOT_COMPUTED = "Không xác định được"


def _ratio(numerator: float | None, denominator: float | None) -> str:
    if numerator is None or not denominator:
        return NOT_APPLICABLE
    return pct(numerator / denominator * 100)


def _billions(value: float) -> str:
    text = bn(value)
    return "0" if text == "-" else text


# -- Header -------------------------------------------------------------------------------------------

def customer_name(state: dict) -> str:
    return state["analysis"].get("customer_name") or "Chưa xác định"


def tax_code(state: dict) -> str:
    return state.get("tax_code") or NOT_APPLICABLE


def analysis_period(state: dict) -> str:
    period = state["analysis"]["period"]
    if not period.window:
        return "Không xác định được"
    return f"{month_label(period.window[0])} – {month_label(period.current)}"


def report_date(state: dict) -> str:
    day = date.fromisoformat(state["report_date"]) if state.get("report_date") else date.today()
    return f"{day:%d/%m/%Y}"


# -- Summary ------------------------------------------------------------------------------------------

def summary(state: dict) -> str:
    analysis = state["analysis"]
    assessment, score = analysis["coverage"], analysis["score"]
    matrix = analysis["matrix"]
    total_in, total_out = matrix["inflow"]["grand_total"], matrix["outflow"]["grand_total"]
    sales = next(r["total"] for r in matrix["inflow"]["rows"] if r["code"] == "IN_01")
    unknown = (next(r["total"] for r in matrix["inflow"]["rows"] if r["code"] == "IN_10")
               + next(r["total"] for r in matrix["outflow"]["rows"] if r["code"] == "OUT_11"))
    lines = [
        f"- **Độ đầy đủ dữ liệu:** {assessment['conclusion']} (mức cảnh báo {assessment['level'].lower()})"
        + (f" do {'; '.join(assessment['reasons'])}." if assessment["reasons"] else "."),
        f"- **Mức độ tin cậy doanh thu:** {score['rating']}"
        + (f", điểm tổng {decimal_comma(score['total'])}/100." if score["computable"] else "."),
        f"- **Quy mô:** tiền vào {_billions(total_in)} tỷ, tiền ra {_billions(total_out)} tỷ trong kỳ; "
        f"tiền thu bán hàng {_billions(sales)} tỷ ({_ratio(sales, total_in)} tiền vào).",
        f"- **Dòng tiền chưa xác định bản chất:** {_ratio(unknown, total_in + total_out)} tổng giá trị giao dịch.",
    ]
    top = analysis["partners"]["customer"]["rows"]
    if top:
        lines.append(f"- **Tập trung khách hàng:** {top[0]['name']} chiếm {pct(top[0]['share'])} tiền thu bán hàng.")
    top = analysis["partners"]["supplier"]["rows"]
    if top:
        lines.append(f"- **Tập trung nhà cung cấp:** {top[0]['name']} chiếm {pct(top[0]['share'])} tiền thanh toán NCC.")
    return "\n".join(lines)


# -- Section 1: data sources -------------------------------------------------------------------------

def source_table(state: dict) -> str:
    unread = [{"source": u["label"], "file": u["file"], "account": NOT_APPLICABLE, "currency": NOT_APPLICABLE,
               "period": NOT_APPLICABLE, "rows": NOT_APPLICABLE,
               "errors": u.get("reason") or "Chưa đọc tự động ở phiên bản này"}
              for u in state["tax_filings"].get("unread", [])]
    columns = [
        Col("Loại dữ liệu", lambda r: r["source"]),
        Col("Tên file", lambda r: r["file"]),
        Col("Tài khoản", lambda r: r["account"]),
        Col("Tiền tệ", lambda r: r["currency"]),
        Col("Kỳ báo cáo", lambda r: r["period"]),
        Col("Số lượng dòng", lambda r: str(r["rows"]), "r"),
    ]
    return build_table(columns, state["analysis"]["inventory"] + unread,
                       empty="_Hồ sơ không có file nào đọc được._")


# -- Section 2: cash flow by category ----------------------------------------------------------------

def _month_header(period, month: str) -> str:
    offset = len(period.window) - 1 - period.window.index(month)
    mark = "" if month in period.full else "*"
    return f"{'T' if offset == 0 else f'T-{offset}'}<br>{month[5:]}/{month[2:4]}{mark}"


def _matrix_table(block: dict, period, total_label: str) -> str:
    columns = [
        NUMBER,
        Col("Loại", lambda r: r["label"], total=bold(total_label)),
        *[Col(_month_header(period, month), lambda r, i=i: bn(r["values"][i]), "r",
              total=bold(bn(block["totals"][i])))
          for i, month in enumerate(period.window)],
        Col("Tổng", lambda r: bn(r["total"]), "r", total=bold(bn(block["grand_total"]))),
    ]
    return build_table(columns, block["rows"])


def inflow_table(state: dict) -> str:
    analysis = state["analysis"]
    return _matrix_table(analysis["matrix"]["inflow"], analysis["period"], "Tổng ghi có")


def outflow_table(state: dict) -> str:
    analysis = state["analysis"]
    return _matrix_table(analysis["matrix"]["outflow"], analysis["period"], "Tổng ghi nợ")


def classification_note(state: dict) -> str:
    period = state["analysis"]["period"]
    partial = [f"{month_label(m)} ({period.coverage[m] * 100:.0f}% số ngày)"
               for m in period.window if m not in period.full]
    if partial:
        return "Tháng đánh dấu * chưa đủ dữ liệu sao kê: " + ", ".join(partial) + "."
    return "Mọi tháng trong kỳ đều đủ dữ liệu sao kê."


# -- Section 3: scale, trend, VAT --------------------------------------------------------------------

def overview_table(state: dict) -> str:
    overview = state["analysis"]["overview"]

    def amount(key: str):
        return lambda r: NOT_APPLICABLE if "unavailable" in r else bn(r[key])

    columns = [
        Col("Chỉ tiêu", lambda r: r["label"]),
        Col("Tổng", lambda r: NOT_COMPUTED if "unavailable" in r else bn(r["total"]), "r"),
        Col("BQ tháng", amount("average"), "r"),
        Col("BQ 3 tháng gần nhất", amount("last3"), "r"),
        Col("BQ 6 tháng gần nhất", amount("last6"), "r"),
        Col("Xu hướng", lambda r: r.get("unavailable") or r["trend"]),
    ]
    note = (f"Bình quân tính trên {overview['full_months']} tháng đủ dữ liệu; xu hướng so sánh "
            "bình quân 3 tháng gần nhất với bình quân tháng.")
    return build_table(columns, overview["rows"]) + "\n\n" + note


def vat_table(state: dict) -> str:
    vat = state["analysis"]["vat"]

    def estimated(key: str):
        return lambda r: bn(r[key]) + (" (ước tính)" if r[f"{key}_estimated"] else "")

    columns = [
        NUMBER,
        Col("Tháng", lambda r: month_label(r["month"]) + ("" if r["full"] else "*")),
        Col("Tổng doanh số VAT đầu vào", estimated("vat_in"), "r"),
        Col("Tổng dòng tiền ra", lambda r: bn(r["outflow"]), "r"),
        Col("Tỷ lệ", lambda r: _ratio(r["outflow"], r["vat_in"]), "r"),
        Col("Tổng doanh số VAT đầu ra", estimated("vat_out"), "r"),
        Col("Tổng dòng tiền vào", lambda r: bn(r["inflow"]), "r"),
        Col("Tỷ lệ", lambda r: _ratio(r["inflow"], r["vat_out"]), "r"),
    ]
    text = build_table(columns, vat["rows"])
    if not vat["has_vat"]:
        text += "\n\nHồ sơ không có tờ khai thuế VAT."
    return text


# -- Section 4: counterparties -----------------------------------------------------------------------

def _lookup_text(row: dict) -> str:
    if not row["tax_code"]:
        return "Chưa có MST để tra cứu"
    info = row.get("lookup")
    if info is None:
        return f"MST {row['tax_code']}; chưa tra cứu được"
    parts = []
    hits = info.get("blwl")
    parts.append("BL/WL: " + (", ".join(h.get("list_type", "") for h in hits) if hits else
                              "không có" if hits is not None else "lỗi tra cứu"))
    financials = info.get("virac") or {}
    if financials:
        year = max(financials)
        f = financials[year]
        parts.append(f"VIRAC {year}: DT {bn(f.get('revenue'))}, TTS {bn(f.get('total_assets'))}, "
                     f"VCSH {bn(f.get('equity'))} tỷ")
    else:
        parts.append("VIRAC: không có dữ liệu")
    debts = info.get("cic") or []
    if debts:
        parts.append(f"CIC: dư nợ {bn(sum(float(d.get('outstanding') or 0) for d in debts))} tỷ, nhóm "
                     f"{max(int(d.get('debt_group') or 1) for d in debts)}")
    else:
        parts.append("CIC: không có dư nợ")
    trade = info.get("trade") or {}
    if trade:
        year = max(trade)
        t = trade[year]
        parts.append(f"XNK {year}: XK {bn(t.get('export_value'))}, NK {bn(t.get('import_value'))} tỷ")
    else:
        parts.append("XNK: không có")
    return "; ".join(parts)


def _partner_notes(side: dict, ledger: str) -> str:
    notes = [f"Top {len(side['rows'])} đối tác chiếm {pct(sum(r['share'] for r in side['rows']))} tổng "
             f"{bn(side['total_value'])} tỷ của nhóm giao dịch này trong kỳ phân tích."]
    if side["unidentified_value"] > 0:
        notes.append(f"{bn(side['unidentified_value'])} tỷ ({pct(side['unidentified_share'])}) chưa xác định "
                     f"được đối tác từ sao kê nên không có trong bảng.")
    if not side["ledger_present"]:
        notes.append(f"Hồ sơ không có sổ chi tiết {ledger}; các cột phát sinh để trống.")
    else:
        start, end = side["ledger_period"]
        span = f"{start:%d/%m/%Y} – {end:%d/%m/%Y}" if start and end else "không rõ"
        notes.append(f"Kỳ sổ {ledger}: {span}; sao kê đủ dữ liệu {len(side['overlap_months'])} tháng trong kỳ sổ. "
                     "Tỷ lệ tính trên tiền thực tế trong kỳ sổ.")
        if side["overlap_limited"]:
            notes.append("Số tháng trùng kỳ còn ít nên tỷ lệ chỉ mang tính tham khảo.")
    return " ".join(notes)


def _sum_in_ledger(key: str):
    return lambda rows: bold(bn(sum(r[key] for r in rows if r["in_ledger"])))


def supplier_table(state: dict) -> str:
    side = state["analysis"]["partners"]["supplier"]
    columns = [
        NUMBER,
        Col("Tên đối tác", lambda r: r["name"] + ("" if r["in_ledger"] else " (không có trong sổ 331)"),
            total=bold("Total")),
        Col("Phát sinh nợ 331", lambda r: bn(r["ledger_debit"]), "r", total=_sum_in_ledger("ledger_debit")),
        Col("Phát sinh có 331", lambda r: bn(r["ledger_credit"]), "r", total=_sum_in_ledger("ledger_credit")),
        Col("Giá trị tiền chuyển ra cho đối tác", lambda r: bn(r["value"]), "r",
            total=lambda rows: bold(bn(sum(r["value"] for r in rows)))),
        Col("Tiền chuyển ra trong kỳ sổ", lambda r: bn(r["cash_in_ledger_period"]), "r",
            total=_sum_in_ledger("cash_in_ledger_period")),
        Col("Tỷ lệ dòng tiền chuyển ra/Phát sinh nợ", lambda r: _ratio(r["cash_in_ledger_period"], r["ledger_debit"]), "r"),
        # Col("Tra cứu thông tin đối tác (BL/WL, quy mô doanh thu/TTS/VCSH, CIC, XNK)", _lookup_text),
    ]
    text = build_table(columns, side["rows"], empty="_Không có giao dịch thuộc nhóm này xác định được đối tác._")
    return text if not side["rows"] else text + "\n\n" + _partner_notes(side, "331")


def customer_table(state: dict) -> str:
    side = state["analysis"]["partners"]["customer"]
    columns = [
        NUMBER,
        Col("Tên đối tác", lambda r: r["name"] + ("" if r["in_ledger"] else " (không có trong sổ 131)"),
            total=bold("Total")),
        Col("Phát sinh nợ 131", lambda r: bn(r["ledger_debit"]), "r", total=_sum_in_ledger("ledger_debit")),
        Col("Phát sinh có 131", lambda r: bn(r["ledger_credit"]), "r", total=_sum_in_ledger("ledger_credit")),
        Col("Giá trị tiền nhận từ đối tác", lambda r: bn(r["value"]), "r",
            total=lambda rows: bold(bn(sum(r["value"] for r in rows)))),
        Col("Tiền nhận trong kỳ sổ", lambda r: bn(r["cash_in_ledger_period"]), "r",
            total=_sum_in_ledger("cash_in_ledger_period")),
        Col("Tỷ lệ dòng tiền nhận/Phát sinh có", lambda r: _ratio(r["cash_in_ledger_period"], r["ledger_credit"]), "r"),
        # Col("Tra cứu thông tin đối tác (BL/WL, quy mô doanh thu/TTS/VCSH, CIC, XNK)", _lookup_text),
    ]
    text = build_table(columns, side["rows"], empty="_Không có giao dịch thuộc nhóm này xác định được đối tác._")
    return text if not side["rows"] else text + "\n\n" + _partner_notes(side, "131")


# -- Section 5: revenue reliability ------------------------------------------------------------------

def score_table(state: dict) -> str:
    score, notes = state["analysis"]["score"], state["analysis"]["indicator_notes"]
    total = decimal_comma(score["total"])
    columns = [
        NUMBER,
        Col("Chỉ tiêu", lambda i: i["label"], total=bold("Điểm tổng")),
        Col("Trọng số", lambda i: f"{i['weight']}%", "r", total=bold("100%")),
        Col("Giá trị", lambda i: NOT_COMPUTED if i["value"] is None
            else i["value"] if isinstance(i["value"], str) else pct(i["value"], 1), "r"),
        Col("Điểm", lambda i: str(i["points"]), "r"),
        Col("Điểm theo trọng số", lambda i: decimal_comma(i["weighted"]), "r",
            total=bold(total) if score["computable"] else f"{bold(NOT_COMPUTED)} (tham khảo {total})"),
        Col("Ghi chú", lambda i: i["missing_reason"] or notes.get(f"score.{i['key']}", "")),
    ]
    return build_table(columns, score["indicators"])


def pillar_table(state: dict) -> str:
    columns = [
        Col("Trụ dữ liệu", lambda p: p["label"]),
        Col("Tình trạng", lambda p: "Có" if p["present"] else "Thiếu"),
        Col("Ghi chú", lambda p: p["reason"] or NOT_APPLICABLE),
    ]
    return build_table(columns, state["analysis"]["score"]["pillars"])


def rating_conclusion(state: dict) -> str:
    score = state["analysis"]["score"]
    head = f"**Xếp hạng mức độ tin cậy doanh thu: {score['rating']}**"
    if score["computable"]:
        head += f" (điểm tổng {decimal_comma(score['total'])}/100)"
    return f"{head}. {score['usage']}"


# -- Appendix -----------------------------------------------------------------------------------------

def label_source_table(state: dict) -> str:
    columns = [
        Col("Cách xác định bản chất", lambda s: s["source"]),
        Col("Số giao dịch", lambda s: str(s["count"]), "r"),
        Col("Giá trị (tỷ đồng)", lambda s: bn(s["value"]), "r"),
        Col("Tỷ trọng giá trị", lambda s: pct(s["share"], 1), "r"),
    ]
    return build_table(columns, state["analysis"]["label_sources"])


def unclassified_table(state: dict) -> str:
    columns = [
        Col("Ngày", lambda t: f"{t.day:%d/%m/%Y}"),
        Col("Tài khoản", lambda t: t.account),
        Col("Vào/Ra", lambda t: DIRECTION[t.direction]),
        Col("Số tiền", lambda t: money(float(t.amount)), "r"),
        Col("Tài khoản đối ứng", lambda t: t.cp_account or NOT_APPLICABLE),
        Col("Tên tài khoản đối ứng", lambda t: t.cp_name or NOT_APPLICABLE),
        Col("Nội dung chuyển khoản", lambda t: (t.narrative or "(không có nội dung)")[:120]),
    ]
    return build_table(columns, state["analysis"]["largest_unclassified"],
                       empty="_Không có giao dịch chưa xác định bản chất._")


REFERENCE_SOURCES = {"registry": "ĐKKD", "t24_accounts": "T24", "t24_transactions": "Sao kê TCB",
                     "fraud": "Fraud", "cic": "CIC", "blwl": "BL/WL", "virac": "VIRAC", "trade": "XNK"}


def missing_data_table(state: dict) -> str:
    facts, reference = state["facts"], state["reference"]
    rows = [{"source": FACT_KEYS[path].category, "data": FACT_KEYS[path].description,
             "reason": facts.missing_reason(path)} for path in FACT_KEYS if not facts.has(path)]
    shown = {row["reason"] for row in rows}
    rows += [{"source": REFERENCE_SOURCES[key], "data": "Truy vấn dữ liệu tham chiếu", "reason": reason}
             for key, reason in reference.get("errors", {}).items() if reason not in shown]
    columns = [
        Col("Nguồn", lambda r: r["source"]),
        Col("Dữ liệu", lambda r: r["data"]),
        Col("Lý do", lambda r: r["reason"]),
    ]
    return build_table(columns, rows, empty="_Không có._")


# -- Template placeholder -> function, in template order ----------------------------------------------

PLACEHOLDERS = {
    "CustomerName": customer_name,
    "TaxCode": tax_code,
    "AnalysisPeriod": analysis_period,
    "ReportDate": report_date,
    "Summary": summary,
    "SourceTable": source_table,
    "InflowTable": inflow_table,
    "OutflowTable": outflow_table,
    "ClassificationNote": classification_note,
    "OverviewTable": overview_table,
    "VatTable": vat_table,
    "SupplierTable": supplier_table,
    "CustomerTable": customer_table,
    "ScoreTable": score_table,
    "RatingConclusion": rating_conclusion,
    "UnclassifiedTable": unclassified_table,
    "MissingDataTable": missing_data_table,
}


def render_report(state: dict, settings: dict) -> str:
    return get_template().render({name: fill(state) for name, fill in PLACEHOLDERS.items()})
