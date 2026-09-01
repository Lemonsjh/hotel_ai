from marketing_diagnosis.visual_diagnosis import build_visual_diagnosis


def _item(result, number):
    return next(item for item in result["items"] if item["standard_item_id"] == number)


def test_reservation_invoice_matches_stable_code_and_closed_status():
    result = build_visual_diagnosis({
        "promotion_status": [{
            "promotion_code": "reservation_invoice",
            "promotion_name": "预约发票",
            "status": "CLOSED",
        }]
    })

    item = _item(result, 20)
    assert item["item_name"] == "预约发票"
    assert item["data_status"] == "zero"
    assert item["score_ratio"] == 0.0
    assert item["item_score"] == 0.0
    assert item["fields"][0]["value"] == "CLOSED"


def test_invoice_name_alias_is_still_supported_without_code():
    result = build_visual_diagnosis({
        "promotion_status": [{"promotion_name": "发票", "status": "OPEN"}]
    })

    item = _item(result, 20)
    assert item["item_name"] == "预约发票"
    assert item["data_status"] == "success"
    assert item["item_score"] == 2.0
