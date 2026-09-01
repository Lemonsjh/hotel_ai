from __future__ import annotations

import argparse
from unittest import mock

from runtime.adapters import database


def test_price_snapshot_preserves_mapping_governance_fields() -> None:
    raw = {
        "rows": [
            {
                "hotel_id": "puyue",
                "source_platform": "meituan",
                "business_date": "2026-08-04",
                "snapshot_time": "2026-08-04 17:15:00",
                "ota_product_id": "mt-13",
                "ota_product_name": "挂牌大床房",
                "ota_sale_price": 404,
                "room_type_id": "py01",
                "room_type_name": "大床房",
                "mapping_id": 13,
                "mapping_status": "AUTO",
                "match_rule": "PRODUCT_ID",
                "mapping_active": True,
                "mapping_resolution_status": "mapped",
                "risk_flags": [],
            }
        ],
        "row_count": 1,
        "risk_flags": [],
        "source_status": "ok",
    }
    coverage = {"requested_platform": "meituan", "tables": {}, "meituan": {"table_row_count": 1, "hotel_row_count": 1}}
    args = argparse.Namespace(hotel_id="puyue", date="2026-08-04", source_platform="meituan", as_of_time=None)

    with mock.patch.object(database, "_ota_price_mapping_coverage", return_value=coverage), mock.patch.object(
        database, "_query_mysql_v4_rows", return_value=raw
    ):
        result = database._query_mysql_ota_price_mapping(object(), args, {})

    snapshot = result["price_snapshots"][0]
    assert snapshot["mapping_id"] == 13
    assert snapshot["mapping_status"] == "AUTO"
    assert snapshot["match_rule"] == "PRODUCT_ID"
    assert snapshot["mapping_active"] is True
    assert snapshot["mapping_resolution_status"] == "mapped"
