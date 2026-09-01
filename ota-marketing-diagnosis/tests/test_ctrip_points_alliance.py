from marketing_diagnosis.ctrip_flow_rules import process


def test_inactive_points_alliance_zeroes_orders_and_amount():
    result = process(
        {
            "sections": {
                "ctrip_promotion_status": [
                    {
                        "activity_code": "points_alliance",
                        "enabled": 0,
                        "status": "NOT_JOINED",
                        "orders_30d": None,
                        "metric_value": None,
                        "metric_unit": "amount",
                        "platform_scope": "ctrip",
                    }
                ]
            }
        }
    )

    item = result["ctrip_items"]["14"]
    fields = {field["label"]: field["value"] for field in item["fields"]}

    assert item["item_score"] == 0
    assert fields["报名状态"] == "未报名"
    assert fields["近30天订单"] == 0
    assert fields["成交金额"] == 0
