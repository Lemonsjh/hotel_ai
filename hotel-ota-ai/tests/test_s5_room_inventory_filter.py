from runtime.s5_room_inventory_filter_patch import (
    filter_s5_candidates_by_room_inventory,
    no_sellable_room_types,
)


def _operating():
    return {
        "status": "ok",
        "payload": {
            "business_date": "2026-08-05",
            "room_type_forecasts": [
                {
                    "stay_date": "2026-08-05",
                    "room_type_id": "RT-CLOSED",
                    "room_type_name": "豪华大床房",
                    "total_rooms": 10,
                    "available_rooms": 0,
                },
                {
                    "stay_date": "2026-08-05",
                    "room_type_id": "RT-OPEN",
                    "room_type_name": "高级双床房",
                    "total_rooms": 8,
                    "available_rooms": 3,
                },
            ],
        },
    }


def test_no_sellable_room_types_uses_available_rooms_zero():
    closed = no_sellable_room_types(
        _operating(),
        target_stay_date="2026-08-05",
    )

    assert list(closed) == ["RT-CLOSED"]
    assert closed["RT-CLOSED"] == {
        "room_type_id": "RT-CLOSED",
        "room_type_name": "豪华大床房",
        "stay_date": "2026-08-05",
        "total_rooms": 10.0,
        "available_rooms": 0.0,
        "reason": "room_type_no_sellable_inventory",
    }


def test_products_for_closed_room_type_are_removed_from_s5_candidates():
    result = filter_s5_candidates_by_room_inventory(
        {
            "status": "ok",
            "candidate_count": 3,
            "eligible_for_s6_count": 3,
            "quality_flags": [],
            "candidates": [
                {
                    "room_type_id": "RT-CLOSED",
                    "ota_product_id": "P-CLOSED-1",
                    "eligibility": "eligible_for_s6_dry_run",
                },
                {
                    "room_type_id": "RT-CLOSED",
                    "ota_product_id": "P-CLOSED-2",
                    "auto_execution_eligible": True,
                },
                {
                    "room_type_id": "RT-OPEN",
                    "ota_product_id": "P-OPEN",
                    "eligibility": "eligible_for_s6_dry_run",
                },
            ],
        },
        operating_result=_operating(),
        target_stay_date="2026-08-05",
    )

    assert [item["ota_product_id"] for item in result["candidates"]] == ["P-OPEN"]
    assert result["candidate_count"] == 1
    assert result["eligible_for_s6_count"] == 1
    assert result["excluded_no_inventory_product_count"] == 2
    assert result["excluded_no_inventory_room_type_count"] == 1
    assert result["quality_flags"] == [
        "excluded_room_type_no_sellable_inventory"
    ]


def test_requested_product_reports_room_inventory_exclusion():
    result = filter_s5_candidates_by_room_inventory(
        {
            "status": "ok",
            "candidate_count": 1,
            "eligible_for_s6_count": 1,
            "candidates": [
                {
                    "room_type_id": "RT-CLOSED",
                    "ota_product_id": "P-CLOSED-1",
                    "eligibility": "eligible_for_s6_dry_run",
                }
            ],
        },
        operating_result=_operating(),
        target_stay_date="2026-08-05",
        requested_ota_product_id="P-CLOSED-1",
    )

    assert result["candidates"] == []
    assert result["candidate_count"] == 0
    assert result["requested_product_excluded_reason"] == (
        "room_type_no_sellable_inventory"
    )
    assert result["blocked_reason"] == (
        "all_matching_products_excluded_no_sellable_inventory"
    )
