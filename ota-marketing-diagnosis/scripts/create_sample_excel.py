from pathlib import Path

from openpyxl import Workbook


def write_sheet(workbook, name, headers, rows):
    sheet = workbook.create_sheet(name)
    sheet.append(headers)
    for row in rows:
        sheet.append(row)


def main():
    workbook = Workbook()
    workbook.remove(workbook.active)
    write_sheet(workbook, "hotel_daily", ["business_date", "room_count", "room_nights", "room_revenue"], [["2026-07-01", 31, 26, 3728], ["2026-07-02", 31, 23, 3280]])
    write_sheet(workbook, "ota_funnel", ["business_date", "platform", "exposure", "views", "paid_orders", "peer_avg_conversion_rate"], [["2026-07-02", "meituan", 504, 65, 5, 0.08]])
    write_sheet(workbook, "products", ["platform", "room_type_name", "product_name", "listed_price", "final_price", "is_group_buy"], [["meituan", "king", "full day", 356, 356, False], ["meituan", "king", "group buy", 356, 139, True]])
    write_sheet(workbook, "reviews", ["platform", "review_date", "rating", "review_text", "is_negative"], [["meituan", "2026-07-01", 5, "clean room", False], ["meituan", "2026-07-02", 3, "slow service", True]])
    write_sheet(workbook, "competitors", ["business_date", "competitor_name", "price", "rank"], [["2026-07-02", "competitor A", 180, 3], ["2026-07-02", "competitor B", 220, 1]])
    out = Path("examples/sample_data.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(out)
    print(out)


if __name__ == "__main__":
    main()
