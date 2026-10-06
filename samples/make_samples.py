"""Build the two synthetic cases the checks run on. Every name and tax code is fictitious.

    python3 samples/make_samples.py
"""

from __future__ import annotations

import csv
import random
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent
NS = "http://kekhaithue.gdt.gov.vn/TKhaiThue"
TCB_HEADER = ["#", "account_number", "currency", "entry_id", "debit_amount", "credit_amount", "narrative",
              "transaction_code", "transaction_name", "date_time", "transaction_type",
              "settlement_account_number", "settlement_customer_name", "settlement_customer_tax_code",
              "settlement_bank_code", "settlement_bank_name"]
MONTHS = [(2025, m) for m in range(7, 13)] + [(2026, m) for m in range(1, 7)]

DEMO = {
    "name": "CÔNG TY TNHH THƯƠNG MẠI MINH AN", "tax_code": "9999000002",
    "tcb": "19039990001", "other": "0011000999001", "other_bank": "NGAN HANG TMCP DEMO",
    "buyers": [("CÔNG TY CỔ PHẦN XÂY DỰNG HÒA BÌNH DEMO", "9999100001", 0.34),
               ("CÔNG TY TNHH VẬT LIỆU PHÚ THỊNH", "9999100002", 0.24),
               ("CÔNG TY TNHH NỘI THẤT TÂN PHÁT", "9999100003", 0.16),
               ("HỘ KINH DOANH TRẦN VĂN LỘC", "", 0.10),
               ("CÔNG TY CỔ PHẦN ĐẦU TƯ SÔNG HỒNG DEMO", "9999100004", 0.16)],
    "suppliers": [("CÔNG TY CỔ PHẦN THÉP VIỆT DEMO", "9999200001", 0.45),
                  ("CÔNG TY TNHH XI MĂNG BẮC HÀ", "9999200002", 0.30),
                  ("CÔNG TY TNHH VẬN TẢI ĐÔNG PHONG", "9999200004", 0.10),
                  ("CÔNG TY TNHH GẠCH MEN ÁNH DƯƠNG", "9999200003", 0.15)],
}


def ascii_upper(text: str) -> str:
    import unicodedata
    text = text.replace("Đ", "D").replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").upper()


def vn_amount(value: int) -> str:
    return f"{value:,}"


def day_in(year: int, month: int, rng: random.Random, low: int = 2, high: int = 27) -> datetime:
    return datetime(year, month, rng.randint(low, high), rng.randint(8, 17), rng.randint(0, 59))


class Tcb:
    def __init__(self, account: str) -> None:
        self.account, self.rows = account, []

    def add(self, when: datetime, direction: str, amount: int, narrative: str, name: str = "Giao dich chuyen tien lien NH",
            code: str = "258", kind: str = "BCDP", cp_account: str = "", cp_name: str = "", cp_tax: str = "") -> None:
        self.rows.append([when, direction, amount, narrative, code, name, kind, cp_account, cp_name, cp_tax])

    def write(self, path: Path) -> None:
        self.rows.sort(key=lambda r: r[0])
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(TCB_HEADER)
            for index, (when, direction, amount, narrative, code, name, kind, cp_acc, cp_name, cp_tax) in enumerate(self.rows, 1):
                writer.writerow([index, self.account, "VND", f"FT{when:%y%j%H%M}{index:05d}",
                                 vn_amount(amount) if direction == "OUT" else "",
                                 vn_amount(amount) if direction == "IN" else "", narrative, code, name,
                                 f"{when.month}/{when.day}/{when:%y} {when:%H:%M}", kind, cp_acc, cp_name, cp_tax, "", ""])


def write_vat(path: Path, case: dict, year: int, period: int, kind: str, sales: int, purchases: int) -> None:
    if kind == "M":
        start, end = date(year, period, 1), (date(year + period // 12, period % 12 + 1, 1) - timedelta(days=1))
        label = f"{period:02d}/{year}"
    else:
        start = date(year, period * 3 - 2, 1)
        end = date(year + (period * 3) // 12, (period * 3) % 12 + 1, 1) - timedelta(days=1)
        label = f"{period}/{year}"
    tax_in, tax_out = purchases // 10, sales // 10
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<HSoThueDTu xmlns="{NS}"><HSoKhaiThue><TTinChung><TTinTKhaiThue>
<TKhaiThue><maTKhai>842</maTKhai><tenTKhai>TỜ KHAI THUẾ GIÁ TRỊ GIA TĂNG (Mẫu số 01/GTGT)</tenTKhai>
<KyKKhaiThue><kieuKy>{kind}</kieuKy><kyKKhai>{label}</kyKKhai><kyKKhaiTuNgay>{start:%d/%m/%Y}</kyKKhaiTuNgay><kyKKhaiDenNgay>{end:%d/%m/%Y}</kyKKhaiDenNgay></KyKKhaiThue></TKhaiThue>
<NNT><mst>{case['tax_code']}</mst><tenNNT>{case['name']}</tenNNT></NNT></TTinTKhaiThue></TTinChung>
<CTieuTKhaiChinh><GiaTriVaThueGTGTHHDVMuaVao><ct23>{purchases}</ct23><ct24>{tax_in}</ct24></GiaTriVaThueGTGTHHDVMuaVao>
<ct25>{tax_in}</ct25><ct26>0</ct26>
<HHDVBRaChiuThueGTGT><ct27>{sales}</ct27><ct28>{tax_out}</ct28></HHDVBRaChiuThueGTGT>
<ct29>0</ct29><HHDVBRaChiuTSuat10><ct32>{sales}</ct32><ct33>{tax_out}</ct33></HHDVBRaChiuTSuat10><ct32a>0</ct32a>
<TongDThuVaThueGTGTHHDVBRa><ct34>{sales}</ct34><ct35>{tax_out}</ct35></TongDThuVaThueGTGTHHDVBRa>
</CTieuTKhaiChinh></HSoKhaiThue></HSoThueDTu>
""", encoding="utf-8")


def write_financial_statement(path: Path, case: dict, year: int, revenue: int, prior_revenue: int) -> None:
    def block(rev: int, cash: int) -> tuple[str, str]:
        cogs = int(rev * 0.88)
        receivable, inventory, fixed = int(rev * 0.12), int(rev * 0.10), int(rev * 0.05)
        assets = cash + receivable + inventory + fixed
        debts = int(assets * 0.55)
        balance = (f"<ct110>{cash}</ct110><ct131>{receivable}</ct131><ct140>{inventory}</ct140><ct150>{fixed}</ct150>"
                   f"<ct200>{assets}</ct200><ct300>{debts}</ct300><ct400>{assets - debts}</ct400><ct500>{assets}</ct500>")
        income = (f"<ct01>{rev}</ct01><ct10>{rev}</ct10><ct11>{cogs}</ct11><ct20>{rev - cogs}</ct20>"
                  f"<ct50>{int(rev * 0.03)}</ct50><ct60>{int(rev * 0.024)}</ct60>")
        return balance, income
    end_balance, end_income = block(revenue, 1_450_000_000)
    start_balance, start_income = block(prior_revenue, 1_100_000_000)
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<HSoThueDTu xmlns="{NS}"><HSoKhaiThue><TTinChung><TTinTKhaiThue>
<TKhaiThue><maTKhai>683</maTKhai><tenTKhai>Bộ báo cáo tài chính (B01a - DNN)(TT133/2016/TT-BTC)</tenTKhai>
<KyKKhaiThue><kieuKy>Y</kieuKy><kyKKhai>{year}</kyKKhai><kyKKhaiTuNgay>01/01/{year}</kyKKhaiTuNgay><kyKKhaiDenNgay>31/12/{year}</kyKKhaiDenNgay></KyKKhaiThue></TKhaiThue>
<NNT><mst>{case['tax_code']}</mst><tenNNT>{case['name']}</tenNNT></NNT></TTinTKhaiThue></TTinChung>
<CTieuTKhaiChinh><bctcDaKiemToan>0</bctcDaKiemToan><SoCuoiNam>{end_balance}</SoCuoiNam><SoDauNam>{start_balance}</SoDauNam></CTieuTKhaiChinh>
<PLuc><PL_KQHDSXKD><NamNay>{end_income}</NamNay><NamTruoc>{start_income}</NamTruoc></PL_KQHDSXKD></PLuc>
</HSoKhaiThue></HSoThueDTu>
""", encoding="utf-8")


def ledger_rows(company: str, title: str, start: date, end: date, entries: list[tuple]) -> list[list[str]]:
    rows = [[company], ["Số 1 phố Demo, Hà Nội"], [title], [f"Từ ngày {start:%d/%m/%Y} đến ngày {end:%d/%m/%Y}"], [],
            ["Đối tượng", "Mã số thuế", "Dư nợ đầu kỳ", "Dư có đầu kỳ", "Phát sinh nợ", "Phát sinh có",
             "Dư nợ cuối kỳ", "Dư có cuối kỳ"]]
    totals = [0, 0]
    for name, tax, debit, credit in entries:
        rows.append([name, tax, "", "", vn_amount(debit), vn_amount(credit),
                     vn_amount(max(debit - credit, 0)) if debit >= credit else "",
                     vn_amount(credit - debit) if credit > debit else ""])
        totals[0] += debit
        totals[1] += credit
    rows.append(["Tổng cộng", "", "", "", vn_amount(totals[0]), vn_amount(totals[1]), "", ""])
    return rows


def make_demo() -> None:
    case, rng = DEMO, random.Random(7)
    target = ROOT / "case_demo"
    shutil.rmtree(target, ignore_errors=True)
    (target / "ho_so_tai_chinh").mkdir(parents=True)
    tcb = Tcb(case["tcb"])
    other: list[tuple] = []
    received = {b[0]: 0 for b in case["buyers"]}
    paid = {s[0]: 0 for s in case["suppliers"]}
    vat = {}
    for index, (year, month) in enumerate(MONTHS):
        growth = 1 + 0.012 * index + rng.uniform(-0.03, 0.03)
        sales_total = int(3_200_000_000 * growth)
        for name, tax, share in case["buyers"]:
            for part in range(3):
                amount = int(sales_total * share / 3 * rng.uniform(0.9, 1.1)) // 1000 * 1000
                received[name] += amount
                when = day_in(year, month, rng)
                if "TRẦN VĂN LỘC" in name:
                    tcb.add(when, "IN", amount, "TRAN VAN LOC chuyen tien hang", "208", "Giao dich Internet banking", "ACMO")
                elif "SÔNG HỒNG" in name:
                    other.append((when, "IN", amount, "CTCP DAU TU SONG HONG DEMO chuyen tien thanh toan hop dong"))
                else:
                    tcb.add(when, "IN", amount, f"{ascii_upper(name)} thanh toan tien hang HD{index}{part}",
                            "259", "Giao dich chuyen tien lien NH", "BIDP", cp_name=ascii_upper(name), cp_tax=tax)
        purchase_total = int(sales_total * 0.80)
        for name, tax, share in case["suppliers"]:
            for part in range(2):
                amount = int(purchase_total * share / 2 * rng.uniform(0.9, 1.1)) // 1000 * 1000
                paid[name] += amount
                when = day_in(year, month, rng)
                if "VẬN TẢI" in name:
                    tcb.add(when, "OUT", amount, f"Minh An chuyen tien cuoc van chuyen cho Cong ty TNHH Van tai Dong Phong")
                elif "GẠCH MEN" in name:
                    other.append((when, "OUT", amount, f"Thanh toan tien gach cho CONG TY TNHH GACH MEN ANH DUONG thang {month}"))
                else:
                    tcb.add(when, "OUT", amount, f"Cty Minh An thanh toan tien hang", cp_name=ascii_upper(name), cp_tax=tax,
                            cp_account=f"1200{tax}")
        tcb.add(datetime(year, month, 25, 10, 0), "OUT", 180_000_000, f"Chi luong thang {month:02d}/{year}")
        tcb.add(datetime(year, month, 26, 10, 0), "OUT", 42_000_000, f"Nop BHXH thang {month:02d}/{year}")
        tcb.add(datetime(year, month, 20, 9, 0), "OUT", 60_000_000, f"Nop thue GTGT ky {month:02d}/{year}")
        tcb.add(datetime(year, month, 15, 9, 0), "OUT", 21_000_000, "Thanh toan tien dien EVN HN")
        tcb.add(datetime(year, month, 25, 21, 0), "OUT", 16_000_000, "", "Thu no lai (LD-IN)", "434", "")
        if (year, month) >= (2026, 1):
            tcb.add(datetime(year, month, 25, 21, 5), "OUT", 300_000_000, "", "Thu no goc (LD-PR)", "420", "")
        transfer = datetime(year, month, 10, 11, 0)
        tcb.add(transfer, "OUT", 300_000_000, "Chuyen tien sang TK cong ty tai NH Demo", cp_account=case["other"])
        other.append((transfer + timedelta(minutes=3), "IN", 300_000_000, "MINH AN chuyen tien tu TK Techcombank"))
        if month in (3, 9):
            tcb.add(day_in(year, month, rng), "OUT", 35_000_000, "Chuyen khoan")
            tcb.add(day_in(year, month, rng), "IN", 22_000_000, "CK")
        vat[(year, month)] = (int(sales_total / 1.1 * rng.uniform(0.97, 1.03)),
                              int(purchase_total / 1.1 * rng.uniform(0.97, 1.03)))
    tcb.add(datetime(2025, 7, 1, 8, 30), "IN", 2_000_000_000, "", "Giai ngan khoan vay", "421", "")
    tcb.add(datetime(2025, 12, 20, 15, 0), "OUT", 100_000_000, "Chuyen tien cho ong Nguyen Van An")
    tcb.add(datetime(2026, 6, 30, 16, 0), "IN", 5_000, "", "Tra lai tien gui", "381", "")
    tcb.write(target / "ho_so_tai_chinh" / "BS_TCB_MINHAN.csv")

    other.sort(key=lambda r: r[0])
    book = Workbook()
    sheet = book.active
    sheet.append(["SAO KÊ TÀI KHOẢN"])
    sheet.append([f"Số tài khoản: {case['other']}"])
    sheet.append([f"Ngân hàng: {case['other_bank']}"])
    sheet.append(["Từ ngày 01/07/2025 đến ngày 30/06/2026"])
    sheet.append([])
    sheet.append(["Ngày giao dịch", "Số chứng từ", "Nội dung", "Ghi nợ", "Ghi có", "Số dư"])
    balance = 250_000_000
    for index, (when, direction, amount, narrative) in enumerate(other, 1):
        balance += amount if direction == "IN" else -amount
        sheet.append([when.strftime("%d/%m/%Y %H:%M:%S"), f"DM{index:06d}", narrative,
                      amount if direction == "OUT" else None, amount if direction == "IN" else None, balance])
    book.save(target / "ho_so_tai_chinh" / "sao_ke_ngan_hang_demo.xlsx")

    start, end = date(2025, 7, 1), date(2026, 6, 30)
    buyers = [(n, t, int(received[n] * 1.03), int(received[n] * 0.98)) for n, t, _ in case["buyers"]]
    with open(target / "ho_so_tai_chinh" / "so_chi_tiet_131_MINHAN.csv", "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(ledger_rows(case["name"], "SỔ TỔNG HỢP PHẢI THU CỦA KHÁCH HÀNG", start, end, buyers))
    suppliers = [(n, t, int(paid[n] * 0.99), int(paid[n] * 1.02)) for n, t, _ in case["suppliers"]]
    book = Workbook()
    for row in ledger_rows(case["name"], "SỔ TỔNG HỢP PHẢI TRẢ NGƯỜI BÁN", start, end, suppliers):
        book.active.append(row)
    book.save(target / "ho_so_tai_chinh" / "so_chi_tiet_331_MINHAN.xlsx")

    for (year, month), (sales, purchases) in vat.items():
        write_vat(target / "ho_so_tai_chinh" / f"to_khai_gtgt_{year}_{month:02d}.xml", case, year, month, "M", sales, purchases)
    revenue_2025 = sum(v[0] for (y, _), v in vat.items() if y == 2025) * 2
    write_financial_statement(target / "ho_so_tai_chinh" / "bctc_2025.xml", case, 2025, revenue_2025, int(revenue_2025 * 0.9))


THIN = {"name": "CÔNG TY TNHH DỊCH VỤ KIM NGÂN DEMO", "tax_code": "9999000003", "tcb": "19039990003"}


def make_thin() -> None:
    case, rng = THIN, random.Random(11)
    target = ROOT / "case_missing_data"
    shutil.rmtree(target, ignore_errors=True)
    (target / "ho_so_tai_chinh").mkdir(parents=True)
    halves = {"BS_KIMNGAN_2025.csv": MONTHS[:3], "BS_KIMNGAN_2026.csv": MONTHS[6:]}
    quarterly = {}
    for filename, months in halves.items():
        tcb = Tcb(case["tcb"])
        for year, month in months:
            first = 1
            last = 30 if month in (4, 6, 9, 11) else 28 if month == 2 else 31
            for _ in range(8):
                tcb.add(day_in(year, month, rng, first, last), "IN", rng.randint(80, 220) * 1_000_000,
                        rng.choice(["CK", "chuyen khoan", "KH chuyen tien dich vu", "NGUYEN THI HOA chuyen tien"]),
                        "208", "Giao dich Internet banking", "ACMO")
            for _ in range(6):
                tcb.add(day_in(year, month, rng, first, last), "OUT", rng.randint(60, 180) * 1_000_000,
                        rng.choice(["Chuyen khoan", "Thanh toan tien thue van phong", "Chi luong"]))
            tcb.add(datetime(year, month, first, 8, 0), "OUT", 1_000_000, "Phi quan ly tai khoan", "Thu phi", "234", "")
            tcb.add(datetime(year, month, last, 17, 0), "IN", 10_000, "", "Tra lai tien gui", "381", "")
            if year == 2026:
                quarterly.setdefault((month - 1) // 3 + 1, 0)
                quarterly[(month - 1) // 3 + 1] += 1_100_000_000
        tcb.write(target / "ho_so_tai_chinh" / filename)
    for quarter, sales in quarterly.items():
        write_vat(target / "ho_so_tai_chinh" / f"to_khai_gtgt_quy_{quarter}_2026.xml", case, 2026, quarter, "Q",
                  sales, int(sales * 0.6))


if __name__ == "__main__":
    make_demo()
    make_thin()
    print("samples/case_demo, samples/case_missing_data written")
