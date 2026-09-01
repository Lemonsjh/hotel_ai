from __future__ import annotations

from runtime.s16_skill_delivery_patch import build_s16_response_contract


def test_s16_anomalous_room_contract_requires_pp_deviation() -> None:
    contract = build_s16_response_contract(
        {
            "dynamic_diagnosis": {
                "room_structure": {
                    "room_type_results": [
                        {
                            "room_type_id": "room-fast",
                            "room_type_name": "至臻・电竞双床房",
                            "sales_status": "significant_fast",
                            "committed_sold": 4,
                            "total_rooms": 5,
                            "expected_sold": 3,
                            "room_gap": 1,
                            "delta_pp": 20.0,
                        }
                    ]
                }
            }
        }
    )

    assert contract["anomalous_room_type_ids"] == ["room-fast"]
    assert any(
        "具体pp偏差" in item
        for item in contract["must_preserve"]
    )
    assert any(
        "省略pp数值" in item
        for item in contract["forbidden"]
    )
