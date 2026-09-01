from __future__ import annotations

import os
from unittest import mock

import pytest

from runtime.feishu_command_router import (
    _build_s6_batch_dry_run,
    _build_s6_real_dry_run,
    _detect_intent,
    _s6_is_hour_room,
    _s6_net_target_price,
    _s6_target_price,
    _s5_ota_product_id,
    route_feishu_command,
)
from runtime.storage import connect, init_schema


def _result(payload: dict) -> dict:
    return {"status": "ok", "payload": {"source_status": "ok", **payload}}


def _query(template: str, _hotel_id: str, **_kwargs: object) -> dict:
    data = {
        "operating_snapshot": _result(
            {"committed_occupancy_rate": 0.9, "room_type_forecasts": [{"room_type_id": "py01", "total_rooms": 4, "committed_sold_rooms": 3, "available_rooms": 1}]}
        ),
        "ota_price_mapping": _result(
            {"price_snapshots": [{"hotel_name": "测试酒店", "channel": "meituan", "ota_product_id": "mt-1", "ota_product_name": "挂牌大床房", "room_type_id": "py01", "room_type_name": "大床房", "current_price": 404, "snapshot_time": "2026-08-04T09:58:00", "mapping_status": "AUTO", "mapping_active": True, "mapping_resolution_status": "mapped", "source_product_id": "mt-1"}]}
        ),
        "ota_business_metrics": _result({"rows": []}),
        "sales_baseline": _result({"rows": []}),
        "ctrip_competition_metrics_30d": _result({"rows": []}),
        "ota_order_loss_monthly": _result({"rows": []}),
    }
    data["ota_price_mapping"]["payload"]["price_snapshots"][0]["commission_rate"] = 0.12
    data["ota_activity_summary"] = _result({"rows": []})
    data["ota_activity_product_detail"] = _result({"rows": []})
    return data[template]


def _guard(*_args: object, **_kwargs: object) -> dict:
    return {
        "source": "active_price_guard_policy",
        "policy_id": "guard-1",
        "version": 1,
        "policy_state": "active",
        "floor_price": 360,
        "ceiling_price": 460,
        "max_increase_pct": 0.15,
        "max_decrease_pct": 0.15,
    }


def _s16() -> dict:
    return {"status": "ok", "target_date": "2026-08-04", "as_of_checkpoint_gap": 1, "daily_remaining_gap": 0}


def _s15() -> dict:
    return {"status": "ok", "baseline": {"status": "ok", "business_date": "2026-08-04", "target_room_nights": 28}}


def test_s6_real_dry_run_binds_the_exact_product_and_price() -> None:
    with mock.patch("runtime.feishu_command_router.database_template_result", side_effect=_query), mock.patch(
        "runtime.feishu_command_router.resolve_price_guard_policy", side_effect=_guard
    ), mock.patch(
        "runtime.feishu_command_router._query_s15_baseline"
    ) as s15, mock.patch(
        "runtime.feishu_command_router._query_s16_after_s15"
    ) as s16, mock.patch(
        "runtime.feishu_command_router._capture_runtime_emit", return_value={"status": "dry_run", "guard": {"passed": True}}
    ) as capture:
        result = _build_s6_real_dry_run(
            message="美团 调价预览 商品ID mt-1 目标价 403 2026-08-04",
            hotel_id="puyue",
            db_path=":memory:",
            as_of_time="2026-08-04T10:00:00",
            auth_config=None,
            chat_id="oc_test",
            chat_type="group",
            user_id="user-1",
            open_id="open-1",
            union_id=None,
            role="owner",
        )

    args = capture.call_args.args[1]
    assert result["runtime_command"] == "s6-price-dry-run --real-product"
    assert result["not_bound_to_s5_decision"] is True
    assert result["direct_product_validation"] is True
    assert args.ota_product_id == "mt-1"
    assert args.old_price == 404
    assert args.normal_price == 403
    assert result["input_price_mode"] == "listing_price_target"
    assert result["net_revenue_preview_status"] == "ok"
    assert result["net_revenue_current"] == pytest.approx(302.192)
    assert result["net_revenue_target"] == pytest.approx(301.44)
    assert args.begin_date == "2026-08-04"
    assert args.hotel_name == "测试酒店"
    s15.assert_not_called()
    s16.assert_not_called()


def test_s6_dry_run_uses_runtime_control_db_for_confirmation_when_not_explicit(tmp_path) -> None:
    control_db = str(tmp_path / "control.sqlite")
    with connect(control_db) as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO hotels (hotel_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("puyue", "测试酒店", "2026-08-04T10:00:00", "2026-08-04T10:00:00"),
        )
    with mock.patch.dict(os.environ, {"HOTEL_OTA_DB": control_db}), mock.patch(
        "runtime.feishu_command_router.database_template_result", side_effect=_query
    ), mock.patch(
        "runtime.feishu_command_router._capture_runtime_emit", return_value={"status": "dry_run", "guard": {"passed": True}}
    ):
        result = _build_s6_real_dry_run(
            message="调价 dry-run 商品ID mt-1 挂牌价=403 生效日=2026-08-04",
            hotel_id="puyue",
            db_path=None,
            as_of_time="2026-08-04T10:00:00",
            auth_config=None,
            chat_id="oc_test",
            chat_type="group",
            user_id="user-1",
            open_id="open-1",
            union_id=None,
            role="owner",
            requester_id="owner-1",
        )

    assert result["confirmation_command"].startswith("确认调价 PRC-")


def test_s6_real_dry_run_requires_an_exact_product_id() -> None:
    result = _build_s6_real_dry_run(
        message="调价预览 目标价 403",
        hotel_id="puyue",
        db_path=":memory:",
        as_of_time="2026-08-04T10:00:00",
        auth_config=None,
        chat_id="oc_test",
        chat_type="group",
        user_id="user-1",
        open_id="open-1",
        union_id=None,
        role="owner",
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "price_task_requires_ota_product_id"


def test_s6_listing_price_command_routes_to_dry_run() -> None:
    message = (
        "\u8c03\u4ef7 \u5546\u54c1ID=mt-1 "
        "\u6302\u724c\u4ef7\u8c03\u5230\u00a5403 \u751f\u6548\u65e5=2026-08-04"
    )

    assert _s6_target_price(message) == 403
    assert _detect_intent(message) == "price_execution_dry_run"


def test_s6_per_room_type_price_change_builds_one_batch_preview_and_token(tmp_path) -> None:
    control_db = str(tmp_path / "control.sqlite")
    with connect(control_db) as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO hotels (hotel_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("puyue", "测试酒店", "2026-08-04T10:00:00", "2026-08-04T10:00:00"),
        )

    def batch_query(template: str, _hotel_id: str, **_kwargs: object) -> dict:
        products = [
            {"hotel_name": "测试酒店", "channel": "meituan", "ota_product_id": "mt-1", "ota_product_name": "大床房挂牌", "room_type_id": "py01", "room_type_name": "大床房", "current_price": 404, "snapshot_time": "2026-08-04T09:58:00", "mapping_status": "AUTO", "mapping_active": True, "mapping_resolution_status": "mapped", "source_product_id": "mt-1", "commission_rate": 0.12},
            {"hotel_name": "测试酒店", "channel": "meituan", "ota_product_id": "mt-hour", "ota_product_name": "大床房 4小时", "room_type_id": "py01", "room_type_name": "大床房", "current_price": 98, "snapshot_time": "2026-08-04T09:58:00", "mapping_status": "AUTO", "mapping_active": True, "mapping_resolution_status": "mapped", "source_product_id": "mt-hour", "commission_rate": 0.12},
            {"hotel_name": "测试酒店", "channel": "meituan", "ota_product_id": "mt-2", "ota_product_name": "双床房挂牌", "room_type_id": "py02", "room_type_name": "双床房", "current_price": 380, "snapshot_time": "2026-08-04T09:58:00", "mapping_status": "AUTO", "mapping_active": True, "mapping_resolution_status": "mapped", "source_product_id": "mt-2", "commission_rate": 0.12},
        ]
        if template == "ota_price_mapping":
            return _result({"price_snapshots": products})
        if template == "operating_snapshot":
            return _result({"room_type_forecasts": [{"room_type_id": "py01", "available_rooms": 1}, {"room_type_id": "py02", "available_rooms": 1}]})
        return _result({"rows": []})

    with mock.patch("runtime.feishu_command_router.database_template_result", side_effect=batch_query) as query, mock.patch(
        "runtime.feishu_command_router._capture_runtime_emit", return_value={"status": "dry_run", "guard": {"passed": True}}
    ):
        result = _build_s6_batch_dry_run(
            message="每个房型下降30元 2026-08-04", hotel_id="puyue", db_path=control_db,
            as_of_time="2026-08-04T10:00:00", auth_config=None, chat_id="oc_test", chat_type="group",
            user_id="user-1", open_id="open-1", union_id=None, role="owner", requester_id="owner-1",
        )

    assert _detect_intent("每个房型下降30元") == "price_execution_dry_run"
    assert result["status"] == "dry_run"
    assert result["batch_dry_run"] is True
    assert [item["ota_product_id"] for item in result["batch_items"]] == ["mt-1", "mt-2"]
    assert [item["execution_price"] for item in result["batch_items"]] == [374.0, 350.0]
    assert result["confirmation_command"].startswith("确认调价 PRC-")
    templates = [call.args[0] for call in query.call_args_list]
    assert templates.count("ota_price_mapping") == 1
    assert templates.count("operating_snapshot") == 1


def test_s6_hour_room_detection_requires_an_explicit_hour_room_pattern() -> None:
    assert not _s6_is_hour_room(
        {"is_hour_room": None, "ota_product_name": "\u8363\u8000\u5f00\u9ed1\u53cc\u5e8a\u623f 24\u5c0f\u65f6\u7ba1\u5bb6\u670d\u52a1"}
    )
    assert _s6_is_hour_room(
        {"is_hour_room": None, "ota_product_name": "\u8363\u8000\u6218\u573a\u5927\u5e8a\u623f 4\u5c0f\u65f6\uff0808:00-14:00\uff09"}
    )
    assert _s6_is_hour_room({"is_hour_room": None, "ota_product_name": "\u8363\u8000\u6218\u573a\u5927\u5e8a\u623f 4\u5c0f\u65f6"})
    assert _s6_is_hour_room({"is_hour_room": 1, "ota_product_name": "\u6b63\u5e38\u5168\u65e5\u623f"})


def test_s6_net_target_applies_the_same_change_ratio_to_listing_price() -> None:
    with mock.patch("runtime.feishu_command_router.database_template_result", side_effect=_query), mock.patch(
        "runtime.feishu_command_router._capture_runtime_emit", return_value={"status": "dry_run", "guard": {"passed": True}}
    ) as capture:
        result = _build_s6_real_dry_run(
            message="\u8c03\u4ef7 dry-run \u5546\u54c1ID mt-1 \u51c0\u6536\u76ee\u6807=220 2026-08-04",
            hotel_id="puyue", db_path=":memory:", as_of_time="2026-08-04T10:00:00",
            auth_config=None, chat_id="oc_test", chat_type="group", user_id="user-1",
            open_id="open-1", union_id=None, role="owner",
        )

    assert _s6_net_target_price("\u51c0\u6536\u76ee\u6807=220") == 220
    assert result["input_price_mode"] == "net_revenue_target"
    assert result["requested_net_revenue_target"] == 220
    assert result["net_revenue_target"] == 219.91
    assert result["net_revenue_current"] == 302.192
    assert result["member_expected_factor"] == 0.85
    assert result["net_revenue_change_pct"] == pytest.approx(220 / 302.192 - 1)
    assert result["execution_price"] == 294
    assert capture.call_args.args[1].normal_price == 294


def test_s6_listing_price_target_must_be_a_whole_yuan() -> None:
    with mock.patch("runtime.feishu_command_router.database_template_result", side_effect=_query):
        result = _build_s6_real_dry_run(
            message="调价 dry-run 商品ID mt-1 挂牌价=403.5 生效日=2026-08-04",
            hotel_id="puyue", db_path=":memory:", as_of_time="2026-08-04T10:00:00",
            auth_config=None, chat_id="oc_test", chat_type="group", user_id="user-1",
            open_id="open-1", union_id=None, role="owner",
        )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "target_listing_price_must_be_whole_yuan"


def test_net_revenue_request_with_s5_parenthesized_product_id_routes_to_s6() -> None:
    message = "\u5c06\u72ec\u4eab\u00b7\u7535\u7ade\u5355\u4eba\u95f4\uff082360632683\uff09\uff1a\u51c0\u6536\u9884\u4f30\u00a5227.71\u964d\u4ef7\u5230210"

    assert _s5_ota_product_id(message) == "2360632683"
    assert _s6_net_target_price(message) == 210
    assert _detect_intent(message) == "price_execution_dry_run"


def test_feishu_price_preview_uses_the_real_s6_handler() -> None:
    with mock.patch("runtime.feishu_command_router.database_source_enabled", return_value=True), mock.patch(
        "runtime.feishu_command_router._build_s6_real_dry_run",
        return_value={
            "status": "dry_run",
            "intent": "price_execution_dry_run",
            "skill_id": "S6",
            "node_id": "N016",
            "runtime_command": "s6-price-dry-run --real-product",
            "live_allowed": False,
        },
    ) as build:
        result = route_feishu_command("调价预览 商品ID mt-1 目标价 403 2026-08-04", role="owner")

    assert result["runtime_command"] == "s6-price-dry-run --real-product"
    assert build.call_count == 1


def test_production_feishu_price_preview_bypasses_demo_fallback() -> None:
    auth_context = {
        "auth_status": "authorized", "user_role": "owner", "principal_id": "owner-1",
        "resolved_hotel_id": "puyue", "auth_backend": "test", "tenant_status": "active",
    }
    with mock.patch("runtime.feishu_command_router.database_source_enabled", return_value=True), mock.patch(
        "runtime.feishu_command_router._build_s6_real_dry_run",
        return_value={
            "status": "dry_run", "intent": "price_execution_dry_run", "skill_id": "S6",
            "node_id": "N016", "runtime_command": "s6-price-dry-run --real-product", "live_allowed": False,
        },
    ) as build, mock.patch("runtime.feishu_command_router.build_auth_context", return_value=auth_context), mock.patch(
        "runtime.feishu_command_router.tenant_scope_gate", return_value={"allowed": True}
    ), mock.patch("runtime.feishu_command_router.permission_gate", return_value={"allowed": True}):
        result = route_feishu_command(
            "调价预览 商品ID mt-1 目标价 403 2026-08-04", role="owner", hotel_id="puyue", force_feishu_auth=True,
        )

    assert result["status"] == "dry_run"
    assert result["runtime_command"] == "s6-price-dry-run --real-product"
    assert build.call_count == 1
