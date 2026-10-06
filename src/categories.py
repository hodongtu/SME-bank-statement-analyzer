"""The 21 cash-flow categories of BRD 2.3, labels verbatim."""

IN, OUT = "IN", "OUT"

INFLOW: dict[str, str] = {
    "IN_01": "Tiền thu từ bán hàng, cung cấp dịch vụ",
    "IN_02": "Nộp tiền mặt",
    "IN_03": "Tiền vay hoặc tiền giải ngân",
    "IN_04": "Tiền góp vốn",
    "IN_05": "Tiền chuyển nội bộ",
    "IN_06": "Tiền thu từ cổ đông hoặc bên liên quan",
    "IN_07": "Tiền hoàn, đảo giao dịch",
    "IN_08": "Tiền giải tỏa ký quỹ, tiền gửi",
    "IN_09": "Tiền lãi, cổ tức hoặc thu nhập khác",
    "IN_10": "Tiền chưa xác định được bản chất",
}

OUTFLOW: dict[str, str] = {
    "OUT_01": "Thanh toán cho nhà cung cấp",
    "OUT_02": "Thanh toán điện, nước",
    "OUT_03": "Rút tiền mặt",
    "OUT_04": "Chi lương, bảo hiểm và thuế",
    "OUT_05": "Trả nợ gốc, lãi và phí ngân hàng",
    "OUT_06": "Chuyển tiền nội bộ",
    "OUT_07": "Góp vốn hoặc cho vay",
    "OUT_08": "Chi cho cổ đông hoặc bên liên quan",
    "OUT_09": "Gửi tiết kiệm, ký quỹ",
    "OUT_10": "Giao dịch hoàn, đảo",
    "OUT_11": "Dòng tiền chưa xác định được bản chất",
}

LABELS: dict[str, str] = {**INFLOW, **OUTFLOW}

UNCLASSIFIED = {IN: "IN_10", OUT: "OUT_11"}
INTERNAL = {IN: "IN_05", OUT: "OUT_06"}
RELATED_PARTY = {IN: "IN_06", OUT: "OUT_08"}
SALES = "IN_01"
SUPPLIER = "OUT_01"


def direction_of(code: str) -> str:
    if code in INFLOW:
        return IN
    if code in OUTFLOW:
        return OUT
    raise KeyError(f"unknown cash-flow category {code!r}")
