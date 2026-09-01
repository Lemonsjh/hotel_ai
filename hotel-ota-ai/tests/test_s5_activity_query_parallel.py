from __future__ import annotations

from threading import Event, Lock

from runtime.s5_activity_query_parallel_patch import install
from runtime import s5_product_net_revenue_patch as target


def test_s5_activity_summary_and_detail_are_queried_in_parallel() -> None:
    install()
    entered: list[str] = []
    lock = Lock()
    both_entered = Event()

    def query(template: str, hotel_id: str, **kwargs: object) -> dict[str, object]:
        assert hotel_id == "hotel-a"
        assert kwargs.get("as_of_time") == "2026-08-11T16:00:00"
        if template in {"ota_activity_summary", "ota_activity_product_detail"}:
            with lock:
                entered.append(template)
                if len(entered) == 2:
                    both_entered.set()
            assert both_entered.wait(timeout=1.0), "activity reads did not overlap"
        return {
            "status": "ok",
            "payload": {"source_status": "ok", "rows": [{"template": template}]},
        }

    summary = target._query_template(
        query,
        "ota_activity_summary",
        hotel_id="hotel-a",
        target_stay_date="2026-08-11",
        as_of_time="2026-08-11T16:00:00",
    )
    detail = target._query_template(
        query,
        "ota_activity_product_detail",
        hotel_id="hotel-a",
        target_stay_date="2026-08-11",
        as_of_time="2026-08-11T16:00:00",
    )

    assert summary["payload"]["rows"][0]["template"] == "ota_activity_summary"
    assert detail["payload"]["rows"][0]["template"] == "ota_activity_product_detail"
    assert sorted(entered) == ["ota_activity_product_detail", "ota_activity_summary"]
    assert getattr(target._query_template, "_S5_ACTIVITY_QUERY_PARALLEL_V1", False) is True
