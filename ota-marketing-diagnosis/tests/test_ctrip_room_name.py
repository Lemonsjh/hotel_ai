from marketing_diagnosis.ctrip_report_v54 import build_html
from marketing_diagnosis.ctrip_room_name_v65 import build_room_name_item


def test_room_name_score_uses_length_and_room_selling_signal():
    item = build_room_name_item(
        {
            "ctrip_goods_price_mapping": [
                {"ota_product_name": "轻奢大床房零压床垫"},
                {"ota_product_name": "标准双床房舒适型"},
                {"ota_product_name": "标间"},
            ]
        }
    )

    assert item["item_score"] == 2.4
    assert item["fields"] == [
        {"label": "售卖商品数", "value": 3},
        {"label": "售卖房型数", "value": 3},
        {"label": "合格房型", "value": 2},
        {"label": "合格房型占比", "value": "66.7%"},
    ]
    assert item["records"][0]["qualified"] is True
    assert item["records"][2]["qualified"] is False


def test_room_name_length_counts_chinese_characters_only():
    item = build_room_name_item(
        {
            "ctrip_goods_price_mapping": [
                {"ota_product_name": "大床房<早>"},
                {"ota_product_name": "大床房舒适型<无早>"},
            ]
        }
    )

    assert item["records"][0]["length"] == 4
    assert item["records"][0]["qualified"] is False
    assert item["records"][1]["length"] == 8
    assert item["records"][1]["qualified"] is True


def test_room_name_card_renders_each_selling_name_as_a_table_row():
    item = build_room_name_item(
        {"ctrip_goods_price_mapping": [{"ota_product_name": "轻奢大床房零压床垫"}]}
    )
    output = build_html({"hotel_name": "测试酒店", "ctrip_items": {"11": item}})
    card = output.split("id='rule-11'", 1)[1].split("id='rule-12'", 1)[0]

    assert "ctrip-room-name-table-v65" in card
    assert "轻奢大床房零压床垫" in card
    assert "<th>识别信息</th>" in card
    assert ">合格</td>" in card
