"""Fill the report template from the analysis. Every word here is fixed Vietnamese text."""

from __future__ import annotations

from datetime import date

from src.facts import FACT_KEYS
from src.utils.report.formatting import NOT_APPLICABLE, bn, money, pct, table
from src.utils.report.templates import get_template
from src.utils.numbers import month_label

DIRECTION = {"IN": "Vào", "OUT": "Ra"}


def _month_headers(period, months: list[str]) -> list[str]:
    last = len(period.window) - 1
    headers = []
    for index, month in enumerate(months):
        offset = last - period.window.index(month)
        mark = "" if month in period.full else "*"
        headers.append(f"{'T' if offset == 0 else f'T-{offset}'}<br>{month[5:]}/{month[2:4]}{mark}")
    return headers


def _matrix_table(block: dict, period, total_label: str) -> str:
    headers = ["STT", "Loại", *_month_headers(period, period.window), "Tổng"]
    rows = [[str(i), r["label"], *[bn(v) for v in r["values"]], bn(r["total"])]
            for i, r in enumerate(block["rows"], start=1)]
    rows.append(["", f"**{total_label}**", *[f"**{bn(v)}**" for v in block["totals"]],
                 f"**{bn(block['grand_total'])}**"])
    return table(headers, rows, "cl" + "r" * (len(headers) - 2))


def _inventory(analysis: dict, filings: dict) -> str:
    rows = [[r["source"], r["file"], r["account"], r["currency"], r["period"], str(r["rows"]), r["errors"]]
            for r in analysis["inventory"]]
    rows += [[u["label"], u["file"], NOT_APPLICABLE, NOT_APPLICABLE, NOT_APPLICABLE, NOT_APPLICABLE,
              "Chưa đọc tự động ở phiên bản này"] for u in filings.get("unread", [])]
    if not rows:
        return "_Hồ sơ không có file nào đọc được._"
    return table(["Loại dữ liệu", "Tên file", "Tài khoản", "Tiền tệ", "Kỳ báo cáo", "Số lượng dòng", "Ghi chú"], rows, "lllllrl")


def _list_or(values, empty: str) -> str:
    return ", ".join(values) if values else empty


def _coverage_table(state: dict) -> str:
    facts, analysis, filings = state["facts"], state["analysis"], state["tax_filings"]
    period = analysis["period"]
    required = len(period.required)
    full = facts.get("stmt.full_months") if facts.has("stmt.full_months") else 0
    missing = [month_label(m) for m in (facts.get("stmt.missing_months") or [])]
    month_cov = pct(full / required * 100) if required else NOT_APPLICABLE

    def fact_or_reason(path: str, show) -> tuple[str, str]:
        if facts.has(path):
            return show(facts.get(path)), ""
        return "Không tính được", facts.missing_reason(path)

    revenue, revenue_note = fact_or_reason("stmt.revenue_coverage_pct", pct)
    if facts.has("stmt.revenue_coverage_pct"):
        revenue_note = "so với " + analysis["revenue_basis"]
    balance, balance_note = fact_or_reason("stmt.balance_error_pct", lambda v: pct(v, 2))
    alerts, alerts_note = fact_or_reason("fraud.alert_accounts", lambda v: _list_or(v, "Không có cảnh báo"))
    unscreened, unscreened_note = fact_or_reason("fraud.unscreened_accounts",
                                                 lambda v: _list_or(v, "Mọi tài khoản đã qua xử lý"))
    absent, absent_note = fact_or_reason("t24.accounts_without_statement",
                                         lambda v: _list_or(v, "Không có"))
                                         
    rows = [
        ["Số tháng mức độ bao phủ dữ liệu", f"{full}/{required} tháng ({month_cov})",
         "Tháng thiếu hoặc chưa đủ: " + _list_or(missing, "không có")],
        ["Mức độ bao phủ dữ liệu doanh thu", revenue, revenue_note],
        ["Tỷ lệ giao dịch sai liên tục số dư", balance, balance_note],
        ["Cảnh báo của Fraud", alerts, alerts_note],
        ["Tài khoản chưa qua xử lý của Fraud", unscreened, unscreened_note],
        ["Tài khoản tại TCB chưa có sao kê", absent, absent_note],
        ["Giao dịch trùng đã loại bỏ", str(filings.get("duplicates", 0)), "trùng tài khoản, mã, thời điểm, số tiền, nội dung"],
        ["Giao dịch ngoại tệ chưa đưa vào phân tích", str(filings.get("foreign", 0)), "chỉ phân tích giao dịch VND"],
        ["Giao dịch nằm ngoài kỳ phân tích", str(analysis["outside_window"]), "không đưa vào bảng tháng"],
    ]
    return table(["Chỉ tiêu", "Kết quả", "Ghi chú"], rows)


def _balance_table(analysis: dict) -> str:
    checks = analysis["balance_checks"]
    if not checks:
        return "_Không có giao dịch để đối chiếu số dư._"
    rows = [[c["account"], c["method"], str(c["checked"]) if c["checked"] else NOT_APPLICABLE, c["status"]]
            for c in checks]
    return table(["Tài khoản", "Cách đối chiếu", "Số giao dịch kiểm tra", "Kết quả"], rows, "llrl")


def _coverage_conclusion(assessment: dict) -> str:
    lines = [f"**Mức cảnh báo: {assessment['level']}. Kết luận: {assessment['conclusion']}.**"]
    if assessment["reasons"]:
        lines.append("Căn cứ: " + "; ".join(assessment["reasons"]) + ".")
    if assessment["unchecked"]:
        lines.append("Chưa kiểm tra được: " + "; ".join(assessment["unchecked"]) + ".")
    return "\n\n".join(lines)


def _classification_note(analysis: dict) -> str:
    period = analysis["period"]
    partial = [f"{month_label(m)} ({period.coverage[m] * 100:.0f}% số ngày)"
               for m in period.window if m not in period.full]
    lines = []
    if partial:
        lines.append("Tháng đánh dấu * chưa đủ dữ liệu sao kê: " + ", ".join(partial) + ".")
    return " ".join(lines) or "Mọi tháng trong kỳ đều đủ dữ liệu sao kê."


def _overview_table(analysis: dict) -> str:
    rows = []
    for row in analysis["overview"]["rows"]:
        if "unavailable" in row:
            rows.append([row["label"], "Không tính được", NOT_APPLICABLE, NOT_APPLICABLE, NOT_APPLICABLE,
                         row["unavailable"]])
            continue
        rows.append([row["label"], bn(row["total"]), bn(row["average"]), bn(row["last3"]),
                     bn(row["last6"]), row["trend"]])
    note = (f'\n\nBình quân tính trên {analysis['overview']['full_months']} tháng đủ dữ liệu; xu hướng so sánh '
            'bình quân 3 tháng gần nhất với bình quân tháng.')
    return table(["Chỉ tiêu", "Tổng", "BQ tháng", "BQ 3 tháng gần nhất", "BQ 6 tháng gần nhất", "Xu hướng"],
                 rows, "lrrrrl") + note


def _ratio(numerator: float | None, denominator: float | None) -> str:
    if numerator is None or not denominator:
        return NOT_APPLICABLE
    return pct(numerator / denominator * 100)


def _vat_table(analysis: dict) -> str:
    vat = analysis["vat"]
    rows = []
    for index, r in enumerate(vat["rows"], start=1):
        label = month_label(r["month"]) + ("" if r["full"] else "*")
        vin = bn(r["vat_in"]) + (" (ước tính)" if r["vat_in_estimated"] else "")
        vout = bn(r["vat_out"]) + (" (ước tính)" if r["vat_out_estimated"] else "")
        rows.append([str(index), label, vin, bn(r["outflow"]), _ratio(r["outflow"], r["vat_in"]),
                     vout, bn(r["inflow"]), _ratio(r["inflow"], r["vat_out"])])
    text = table(["STT", "Tháng", "Tổng doanh số VAT đầu vào", "Tổng dòng tiền ra", "Tỷ lệ",
                  "Tổng doanh số VAT đầu ra", "Tổng dòng tiền vào", "Tỷ lệ"], rows, "clrrrrrr")
    if not vat["has_vat"]:
        text += "\n\nHồ sơ không có tờ khai thuế VAT."
    return text


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


def _partner_table(side: dict) -> str:
    ledger = "331" if side["side"] == "supplier" else "131"
    if side["side"] == "supplier":
        heads = ["Giá trị tiền chuyển ra cho đối tác", "Tiền chuyển ra trong kỳ sổ",
                 "Tỷ lệ dòng tiền chuyển ra/Phát sinh nợ"]
        basis = "ledger_debit"
    else:
        heads = ["Giá trị tiền nhận từ đối tác", "Tiền nhận trong kỳ sổ", "Tỷ lệ dòng tiền nhận/Phát sinh có"]
        basis = "ledger_credit"
    headers = ["STT", "Tên đối tác", f"Phát sinh nợ {ledger}", f"Phát sinh có {ledger}", *heads]
    rows = []
    for index, r in enumerate(side["rows"], start=1):
        name = r["name"] + ("" if r["in_ledger"] else f" (không có trong sổ {ledger})")
        rows.append([str(index), name, bn(r["ledger_debit"]), bn(r["ledger_credit"]), bn(r["value"]),
                     bn(r["cash_in_ledger_period"]), _ratio(r["cash_in_ledger_period"], r[basis]),
                     _lookup_text(r)])
    if not rows:
        return "_Không có giao dịch thuộc nhóm này xác định được đối tác._"
    in_ledger = [r for r in side["rows"] if r["in_ledger"]]
    rows.append(["", "**Total**", f"**{bn(sum(r['ledger_debit'] for r in in_ledger))}**",
                 f"**{bn(sum(r['ledger_credit'] for r in in_ledger))}**",
                 f"**{bn(sum(r['value'] for r in side['rows']))}**",
                 f"**{bn(sum(r['cash_in_ledger_period'] for r in in_ledger))}**", "", ""])
    text = table(headers, rows, "clrrrrrl")
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
    return text + "\n\n" + " ".join(notes)


def _indicator_value(indicator: dict) -> str:
    value = indicator["value"]
    if value is None:
        return "Không tính được"
    return value if isinstance(value, str) else pct(value, 1)


def _score_table(analysis: dict) -> str:
    score, notes = analysis["score"], analysis["indicator_notes"]
    rows = []
    for index, ind in enumerate(score["indicators"], start=1):
        note = ind["missing_reason"] or notes.get(f"score.{ind['key']}", "")
        rows.append([str(index), ind["label"], f"{ind['weight']}%", _indicator_value(ind),
                     str(ind["points"]), format(ind["weighted"], ".1f").replace(".", ","), note])
    total = format(score["total"], ".1f").replace(".", ",")
    rows.append(["", "**Điểm tổng**", "**100%**", "", "",
                 f"**{total}**" if score["computable"] else f"**Không tính được** (tham khảo {total})", ""])
    return table(["STT", "Chỉ tiêu", "Trọng số", "Giá trị", "Điểm", "Điểm theo trọng số", "Ghi chú"], rows, "clrrrrl")


def _pillar_table(analysis: dict) -> str:
    rows = [[p["label"], "Có" if p["present"] else "Thiếu", p["reason"] or NOT_APPLICABLE]
            for p in analysis["score"]["pillars"]]
    return table(["Trụ dữ liệu", "Tình trạng", "Ghi chú"], rows)


def _rating(analysis: dict) -> str:
    score = analysis["score"]
    head = f"**Xếp hạng mức độ tin cậy doanh thu: {score['rating']}**"
    if score["computable"]:
        head += f" (điểm tổng {format(score['total'], '.1f').replace('.', ',')}/100)"
    return f"{head}. {score['usage']}"


def _source_table(analysis: dict) -> str:
    rows = [[s["source"], str(s["count"]), bn(s["value"]), pct(s["share"], 1)] for s in analysis["label_sources"]]
    return table(["Cách xác định bản chất", "Số giao dịch", "Giá trị (tỷ đồng)", "Tỷ trọng giá trị"], rows, "lrrr")


def _unclassified_table(analysis: dict) -> str:
    items = analysis["largest_unclassified"]
    if not items:
        return "_Không có giao dịch chưa xác định bản chất._"
    rows = [[f"{t.day:%d/%m/%Y}", t.account, DIRECTION[t.direction], money(float(t.amount)),
             (t.narrative or "(không có nội dung)")[:120]] for t in items]
    return table(["Ngày", "Tài khoản", "Vào/Ra", "Số tiền", "Nội dung chuyển khoản"], rows, "lllrl")


def _missing_table(state: dict) -> str:
    facts, reference = state["facts"], state["reference"]
    rows = [[FACT_KEYS[path].category, FACT_KEYS[path].description, facts.missing_reason(path)]
            for path in FACT_KEYS if not facts.has(path)]
    labels = {"registry": "ĐKKD", "t24_accounts": "T24", "fraud": "Fraud", "cic": "CIC",
              "blwl": "BL/WL", "virac": "VIRAC", "trade": "XNK"}
    shown = {row[2] for row in rows}
    rows += [[labels[key], "Truy vấn dữ liệu tham chiếu", reason]
             for key, reason in reference.get("errors", {}).items() if reason not in shown]
    if not rows:
        return "_Không có._"
    return table(["Nguồn", "Dữ liệu", "Lý do"], rows)


def _billions(value: float) -> str:
    text = bn(value)
    return "0" if text == "-" else text


def _summary(state: dict) -> str:
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
        + (f", điểm tổng {format(score['total'], '.1f').replace('.', ',')}/100." if score["computable"] else "."),
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


def render_report(state: dict, settings: dict) -> str:
    analysis = state["analysis"]
    period = analysis["period"]
    report_date = date.fromisoformat(state["report_date"]) if state.get("report_date") else date.today()
    values = {
        "CustomerName": analysis.get("customer_name") or "Chưa xác định",
        "TaxCode": state.get("tax_code") or NOT_APPLICABLE,
        "AnalysisPeriod": (f"{month_label(period.window[0])} – {month_label(period.current)}"
                       if period.window else "Không xác định được"),
        "ReportDate": f"{report_date:%d/%m/%Y}",
        "Summary": _summary(state),
        "SourceTable": _inventory(analysis, state["tax_filings"]),
        "CoverageTable": _coverage_table(state),
        "BalanceTable": _balance_table(analysis),
        "CoverageConclusion": _coverage_conclusion(analysis["coverage"]),
        "InflowTable": _matrix_table(analysis["matrix"]["inflow"], period, "Tổng ghi có"),
        "OutflowTable": _matrix_table(analysis["matrix"]["outflow"], period, "Tổng ghi nợ"),
        "ClassificationNote": _classification_note(analysis),
        "OverviewTable": _overview_table(analysis),
        "VatTable": _vat_table(analysis),
        "SupplierTable": _partner_table(analysis["partners"]["supplier"]),
        "CustomerTable": _partner_table(analysis["partners"]["customer"]),
        "ScoreTable": _score_table(analysis),
        "PillarTable": _pillar_table(analysis),
        "RatingConclusion": _rating(analysis),
        "LabelSourceTable": _source_table(analysis),
        "UnclassifiedTable": _unclassified_table(analysis),
        "MissingDataTable": _missing_table(state),
    }
    return get_template().render(values)
