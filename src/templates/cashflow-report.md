---
name: cashflow-report
description: Cash-flow analysis from bank statements, structured as BRD sections 2.1 to 2.6 (report text is Vietnamese)
---
# PHÂN TÍCH DÒNG TIỀN THEO SAO KÊ TÀI KHOẢN

| Tên khách hàng | Mã số thuế | Kỳ báo cáo | Ngày tạo |
|---|---|---|---|
| {{CustomerName}} | {{TaxCode}} | {{AnalysisPeriod}} | {{ReportDate}} |

## Tóm tắt

{{Summary}}

## 1. Nguồn dữ liệu

{{SourceTable}}

## 2. Phân loại giao dịch

### a) Dòng tiền vào (đơn vị: tỷ đồng)

{{InflowTable}}

### b) Dòng tiền ra (đơn vị: tỷ đồng)

{{OutflowTable}}

{{ClassificationNote}}

## 3. Quy mô, xu hướng và mức độ ổn định dòng tiền

### a) Tổng quan dòng tiền (đơn vị: tỷ đồng)

{{OverviewTable}}

### b) Dòng tiền so với diễn biến VAT 12 tháng (đơn vị: tỷ đồng)

{{VatTable}}

## 4. Cơ cấu dòng tiền theo đối tác

### a) Đối tác đầu vào: thanh toán cho nhà cung cấp, đối chiếu sổ 331 (đơn vị: tỷ đồng)

{{SupplierTable}}

### b) Đối tác đầu ra: thu tiền bán hàng, đối chiếu sổ 131 (đơn vị: tỷ đồng)

{{CustomerTable}}

## 5. Mức độ tin cậy doanh thu theo dòng tiền

{{ScoreTable}}

{{RatingConclusion}}

## Phụ lục


### A. Giao dịch chưa xác định bản chất có giá trị lớn

{{UnclassifiedTable}}

### B. Dữ liệu chưa thu thập được

{{MissingDataTable}}
