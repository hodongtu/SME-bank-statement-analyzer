"""Financial statements (BCTC) B01a-DNN filed as e-tax XML become a FinancialStatementSummary here.

A BCTC in PDF is read by the IT document service; its adapter builds the same FinancialStatementSummary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.extraction.contract import FinancialStatementSummary
from src.utils.reading.etax_xml import FilingHeader, column_codes, find, load_filing, main_block, text, year_of

REVENUE_LINE = "Doanh thu bán hàng và cung cấp dịch vụ"

_B01A_BALANCE = {
    "ct110": "Tiền và các khoản tương đương tiền",   # cash
    "ct130": "Các khoản phải thu",
    "ct131": "Phải thu khách hàng",                   # accounts_receivable
    "ct132": "Trả trước người bán",                   # prepaid_suppliers
    "ct136": "Các khoản phải thu khác",               # other_receivables
    "ct140": "Hàng tồn kho",                          # inventory
    "ct141": "Hàng tồn kho",
    "ct150": "Tài sản cố định",
    "ct151": "Nguyên giá tài sản cố định",
    "ct152": "Giá trị hao mòn luỹ kế",
    "ct200": "TỔNG CỘNG TÀI SẢN",                     # total_assets
    "ct300": "NỢ PHẢI TRẢ",                           # total_liabilities
    "ct311": "Phải trả người bán",                    # accounts_payable
    "ct312": "Người mua trả tiền trước",              # customer_advances
    "ct313": "Thuế và các khoản phải nộp Nhà nước",
    "ct314": "Phải trả người lao động",
    "ct400": "VỐN CHỦ SỞ HỮU",                        # equity
    "ct411": "Vốn góp của chủ sở hữu",
    "ct417": "Lợi nhuận sau thuế chưa phân phối",
    "ct500": "TỔNG CỘNG NGUỒN VỐN",
}

_B02_INCOME = {
    "ct01": REVENUE_LINE,                                         # gross_revenue
    "ct02": "Các khoản giảm trừ doanh thu",
    "ct10": "Doanh thu thuần về bán hàng và cung cấp dịch vụ",    # net_revenue
    "ct11": "Giá vốn hàng bán",                                   # cogs
    "ct20": "Lợi nhuận gộp về bán hàng và cung cấp dịch vụ",      # gross_profit
    "ct21": "Doanh thu hoạt động tài chính",
    "ct22": "Chi phí tài chính",                                  # financial_expense
    "ct23": "Chi phí lãi vay",                                    # interest_expense
    "ct24": "Chi phí quản lý kinh doanh",
    "ct30": "Lợi nhuận thuần từ hoạt động kinh doanh",
    "ct31": "Thu nhập khác",
    "ct32": "Chi phí khác",
    "ct40": "Lợi nhuận khác",
    "ct50": "Lợi nhuận trước thuế",                               # profit_before_tax
    "ct51": "Chi phí thuế thu nhập doanh nghiệp",
    "ct60": "Lợi nhuận sau thuế thu nhập doanh nghiệp",           # net_profit
}

_LCTT_CASHFLOW = {
    "ct20": "Lưu chuyển tiền thuần từ hoạt động kinh doanh",
    "ct30": "Lưu chuyển tiền thuần từ hoạt động đầu tư",
    "ct40": "Lưu chuyển tiền thuần từ hoạt động tài chính",
    "ct50": "Lưu chuyển tiền thuần trong kỳ",
    "ct60": "Tiền và tương đương tiền đầu kỳ",
    "ct70": "Tiền và tương đương tiền cuối kỳ",
}

FinancialsRead = tuple[FinancialStatementSummary | None, str, str, str]   # (summary, tax code, name, error)


def _statement(values_by_year: dict[str, dict[str, float]], code_labels: dict[str, str]) -> dict[str, Any]:
    """One statement as line items with a value column per year."""

    years = [year for year in values_by_year if year]
    line_items = []
    for code, label in code_labels.items():
        values = {year: values_by_year[year][code] for year in years if code in values_by_year[year]}
        if values:
            line_items.append([label, None, *[values.get(year) for year in years], None])
    return {"unit": "VNĐ", "source_unit": "dong", "page": None, "years": years,
            "item_columns": ["label", "code", *years, "page"], "line_items": line_items}


def _check_identities(balance: dict[str, dict[str, float]], income: dict[str, dict[str, float]]) -> list[str]:
    """Where the filing's own arithmetic fails to hold."""

    problems: list[str] = []
    for year, values in balance.items():
        total, debts, equity = (values.get(c) for c in ("ct200", "ct300", "ct400"))
        if None not in (total, debts, equity) and abs(debts + equity - total) > 1:
            problems.append(
                f"{year}: bảng cân đối không cân — nợ phải trả {debts:,.0f} cộng "
                f"vốn chủ sở hữu {equity:,.0f} khác tổng tài sản {total:,.0f}."
            )
        funding = values.get("ct500")
        if None not in (total, funding) and abs(funding - total) > 1:
            problems.append(f"{year}: tổng nguồn vốn {funding:,.0f} khác tổng tài sản {total:,.0f}.")
    for year, values in income.items():
        gross, revenue, cogs = (values.get(c) for c in ("ct20", "ct10", "ct11"))
        if None in (gross, revenue, cogs):
            continue
        if abs(revenue - cogs - gross) > 1:
            problems.append(
                f"{year}: lợi nhuận gộp {gross:,.0f} khác doanh thu thuần "
                f"{revenue:,.0f} trừ giá vốn {cogs:,.0f}."
            )
    return problems


def parse_financial_statement(root: Any, header: FilingHeader) -> tuple[dict[str, Any] | None, str]:
    """B01a-DNN and its appendices as balance sheet, income statement and cash flow, or the error."""

    period = find(root, "KyKKhaiThue")
    end_year = year_of(text(period, "kyKKhaiDenNgay")) or f"Năm {text(period, 'kyKKhai')}"
    start_year = year_of(text(period, "kyKKhaiTuNgay"))
    # The opening column is the prior year's close, whatever the filing calls it.
    prior_year = f"Năm {int(end_year.split()[-1]) - 1}" if end_year.split()[-1].isdigit() else ""
    if start_year == end_year:
        start_year = prior_year

    main = main_block(root)
    income_node, cashflow_node = find(root, "PL_KQHDSXKD"), find(root, "PL_LCTTTT")
    balance = {end_year: column_codes(main, "SoCuoiNam"), start_year: column_codes(main, "SoDauNam")}
    income = {end_year: column_codes(income_node, "NamNay"), start_year: column_codes(income_node, "NamTruoc")}
    cashflow = {end_year: column_codes(cashflow_node, "NamNay"), start_year: column_codes(cashflow_node, "NamTruoc")}
    balance = {y: v for y, v in balance.items() if y and v}
    income = {y: v for y, v in income.items() if y and v}
    cashflow = {y: v for y, v in cashflow.items() if y and v}

    if not balance:
        return None, "Không đọc được khối SoCuoiNam/SoDauNam của bảng cân đối."
    problems = _check_identities(balance, income)
    if problems:
        return None, "Số liệu trong XML không tự nhất quán: " + " ".join(problems)

    return {
        "customer": {"name": header.taxpayer_name or "", "tax_code": header.taxpayer_id or ""},
        "document_type": header.form_name or "BCTC",
        "reporting_period": {
            "period_label": end_year,
            "start_date": text(period, "kyKKhaiTuNgay"),
            "end_date": text(period, "kyKKhaiDenNgay"),
            "comparative_period_label": start_year,
        },
        "is_audited": text(main, "bctcDaKiemToan") == "1",
        "balance_sheet": _statement(balance, _B01A_BALANCE),
        "income_statement": _statement(income, _B02_INCOME),
        "cash_flow_statement": _statement(cashflow, _LCTT_CASHFLOW),
    }, ""


def summarise(statement: dict[str, Any], filename: str, source_format: str, tax_code: str,
              name: str) -> FinancialStatementSummary:
    """What the analysis uses from a statement: revenue by year, period, size."""

    income = statement.get("income_statement") or {}
    revenue: dict[int, float] = {}
    for label, _, *values in income.get("line_items", []):
        if label == REVENUE_LINE:
            for year_label, value in zip(income.get("years", []), values):
                if value is not None:
                    revenue[int(year_label.split()[-1])] = float(value)
    return FinancialStatementSummary(
        filename=filename, source_format=source_format, tax_code=tax_code, taxpayer_name=name,
        period_label=(statement.get("reporting_period") or {}).get("period_label", "—"),
        revenue_by_year=revenue, line_count=len(income.get("line_items", [])))


def read_financial_statement(path: str | Path) -> FinancialsRead:
    """Entry point for a BCTC this project reads itself (e-tax XML)."""

    path = Path(path)
    root, header = load_filing(str(path))
    if root is None:
        return None, "", "", header.error
    if header.kind != "financial_statement":
        return None, header.taxpayer_id, header.taxpayer_name, header.error or "Không phải BCTC B01a-DNN"
    statement, error = parse_financial_statement(root, header)
    if statement is None:
        return None, header.taxpayer_id, header.taxpayer_name, error
    return (summarise(statement, path.name, "xml", header.taxpayer_id, header.taxpayer_name),
            header.taxpayer_id, header.taxpayer_name, "")
