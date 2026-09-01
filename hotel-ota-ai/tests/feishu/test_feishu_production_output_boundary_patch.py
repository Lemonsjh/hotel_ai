from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from runtime.feishu_production_output_boundary_patch import _patch_router


def _fake_router() -> SimpleNamespace:
    router = SimpleNamespace()

    def business_date(result: dict[str, Any]) -> str:
        return str(
            result.get("business_date")
            or result.get("demo_business_date")
            or result.get("data_business_date")
            or "-"
        )

    def render_feishu_output(result: dict[str, Any], *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"business_date": business_date(result)}

    def build_feishu_send_payload(result: dict[str, Any], *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"business_date": business_date(result)}

    def safe_route_feishu_command(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        result = {
            "status": "ok",
            "data_source_type": "mysql_db",
            "freshness_status": "fresh",
            "business_result_generated": True,
            "data_business_date": "2026-08-11",
            "demo_dataset_id": "hotel-ota-demo-v1",
            "demo_business_date": "2026-06-11",
            "demo_run_id": "demo-run",
            "metric_value": 17,
        }
        result["data_source_type"] = kwargs.get("data_source_type", result["data_source_type"])
        if kwargs.get("render", True):
            result["rendered"] = router.render_feishu_output(result, None)
            result["send_payload"] = router.build_feishu_send_payload(result, role="owner")
        return result

    router.render_feishu_output = render_feishu_output
    router.build_feishu_send_payload = build_feishu_send_payload
    router.safe_route_feishu_command = safe_route_feishu_command
    return router


def test_production_output_strips_only_demo_provenance_before_render_and_return() -> None:
    router = _fake_router()
    _patch_router(router)

    result = router.safe_route_feishu_command("S10", production_feishu=True)

    for key in ("demo_dataset_id", "demo_business_date", "demo_run_id"):
        assert key not in result
    assert result["rendered"]["business_date"] == "2026-08-11"
    assert result["send_payload"]["business_date"] == "2026-08-11"
    assert result["metric_value"] == 17
    assert result["data_source_type"] == "mysql_db"
    assert result["freshness_status"] == "fresh"
    assert result["business_result_generated"] is True


def test_non_production_real_output_also_strips_inherited_demo_metadata() -> None:
    router = _fake_router()
    _patch_router(router)

    router.safe_route_feishu_command("S10", production_feishu=True)
    result = router.safe_route_feishu_command("S10", production_feishu=False)

    for key in ("demo_dataset_id", "demo_business_date", "demo_run_id"):
        assert key not in result
    assert result["rendered"]["business_date"] == "2026-08-11"
    assert result["send_payload"]["business_date"] == "2026-08-11"


def test_explicit_local_demo_keeps_its_own_provenance() -> None:
    router = _fake_router()
    _patch_router(router)

    result = router.safe_route_feishu_command(
        "S10",
        production_feishu=False,
        data_source_type="demo_data",
    )

    assert result["demo_dataset_id"] == "hotel-ota-demo-v1"
    assert result["demo_business_date"] == "2026-06-11"
    assert result["demo_run_id"] == "demo-run"
