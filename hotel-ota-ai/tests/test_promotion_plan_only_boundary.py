from argparse import Namespace

from runtime.decisions import promotion


def test_s8_display_result_exposes_readonly_boundary(monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(promotion, "emit", emitted.append)

    promotion._emit_s8_display_result({"skill_id": "S8", "evidence": {}})

    result = emitted[0]
    assert result["skill_id"] == "S8"
    assert result["write_performed"] is False
    assert result["live_allowed"] is False
    assert result["execution_boundary"] == {
        "delivery_owner": "S8",
        "delivery_channel": "feishu",
        "execution_supported": False,
        "task_creation_supported": False,
        "approval_supported": False,
        "ota_write_attempted": False,
        "boundary_reason": "s8_display_only",
    }
    assert "approval_id" not in result
    assert "execution_status" not in result
    assert "promotion_execution_task" not in result


def test_promotion_plan_only_displays_s8_source_data(monkeypatch):
    emitted: list[dict] = []
    calls: list[tuple[str, str | None]] = []

    def fake_query(hotel_id: str, *, as_of_time: str | None = None):
        calls.append((hotel_id, as_of_time))
        return {
            "status": "ok",
            "payload": {
                "source_status": "ok",
                "source_table": "meituan_ota_promotion_performance_30d",
                "data_business_date": "2026-08-06",
                "data_snapshot_time": "2026-08-07 09:30:00",
                "rows": [
                    {
                        "plan_name": "计划A",
                        "launch_name": "单元A",
                        "promotion_name": "推广通",
                        "spend_amount": 100,
                        "cash_spend_amount": 80,
                        "click_count": 10,
                        "booking_order_count": 2,
                        "room_night_count": 2,
                        "booking_order_amount": 500,
                    }
                ],
            },
        }

    monkeypatch.setattr(promotion, "query_s8_promotion_display", fake_query)
    monkeypatch.setattr(promotion, "emit", emitted.append)

    promotion.promotion_plan(
        Namespace(
            hotel_id="hotel-001",
            as_of_time="2026-08-07 10:00:00",
        )
    )

    assert calls == [("hotel-001", "2026-08-07 10:00:00")]
    result = emitted[0]
    assert result["status"] == "ok"
    assert result["skill_id"] == "S8"
    assert result["recommendations"] == []
    assert result["actions"] == []
    assert result["approval_required"] is False
    assert result["write_performed"] is False
    assert result["live_allowed"] is False
    display = result["evidence"]["promotion_display"]
    assert display["source_table"] == "meituan_ota_promotion_performance_30d"
    assert display["item_count"] == 1
    assert display["items"][0]["plan_name"] == "计划A"
    assert "promotion_status" not in display["items"][0]
    assert "promotion_action" not in display["items"][0]


def test_s11_legacy_entrypoint_is_isolated_from_s8_display(monkeypatch):
    captured: dict = {}

    def fake_s11(args):
        captured["hotel_id"] = args.hotel_id

    def fail_if_s8_called(args):
        raise AssertionError("S11 must not call the S8 display path")

    monkeypatch.setattr(promotion, "_emit_s11_promotion_suggestion", fake_s11)
    monkeypatch.setattr(promotion, "_emit_promotion_plan", fail_if_s8_called)

    promotion.promotion_execute(Namespace(hotel_id="hotel-001"))

    assert captured == {"hotel_id": "hotel-001"}
