from __future__ import annotations

import json
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime.common import PACKAGE_ROOT
from runtime.field_coverage import calculate_field_coverage
from runtime.reports.external_ota_html_report import generate_external_ota_html_report


DEMO_DATA_DIR = PACKAGE_ROOT / "examples" / "demo_data"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=None)
def load_demo_json(name: str) -> dict[str, Any]:
    return _read_json(DEMO_DATA_DIR / name)


def load_demo_manifest() -> dict[str, Any]:
    return load_demo_json("demo_manifest.json")


def load_demo_fact(name: str) -> dict[str, Any]:
    return load_demo_json(name)


def demo_safety_flags() -> dict[str, Any]:
    manifest = load_demo_manifest()
    return {
        "demo_dataset_id": manifest["demo_dataset_id"],
        "hotel_id": manifest["hotel_id"],
        "hotel_name": manifest["hotel_name"],
        "demo_business_date": manifest["demo_business_date"],
        "data_business_date": manifest["demo_business_date"],
        "data_source_type": "demo_data",
        "freshness_status": "demo_data",
        "business_status": "demo_or_historical",
        "generated_by_runtime": True,
        "today_label_allowed": False,
        "approval_data_allowed": False,
        "approval_preview_allowed": True,
        "formal_approval_allowed": False,
        "live_allowed": False,
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def demo_run_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def business_snapshot() -> dict[str, Any]:
    data = dict(load_demo_fact("business_snapshot.json"))
    data.update(demo_safety_flags())
    return data


def room_types() -> list[dict[str, Any]]:
    return [dict(item) for item in load_demo_fact("room_types.json").get("room_types", [])]


def room_type(room_type_id: str = "KING") -> dict[str, Any]:
    wanted = str(room_type_id).upper()
    for item in room_types():
        if str(item.get("room_type_id")).upper() == wanted:
            return item
    raise KeyError(f"missing demo room type {room_type_id}")


def orders_aggregate() -> dict[str, Any]:
    data = dict(load_demo_fact("orders_aggregate.json"))
    data.update(demo_safety_flags())
    return data


def market_context() -> dict[str, Any]:
    data = dict(load_demo_fact("market_context.json"))
    data.update(demo_safety_flags())
    return data


def progress_deviation() -> dict[str, Any]:
    data = dict(load_demo_fact("progress_deviation.json"))
    data.update(demo_safety_flags())
    return data


def promotion_fact() -> dict[str, Any]:
    data = dict(load_demo_fact("promotion.json"))
    data.update(demo_safety_flags())
    return data


def execution_preview() -> dict[str, Any]:
    data = dict(load_demo_fact("execution_preview.json"))
    king = room_type(str(data.get("room_type_id") or "KING"))
    data["room_type_name"] = king.get("room_type_name")
    for field in ("floor_price", "ceiling_price", "candidate_price", "conservative_price", "current_price"):
        if field in king:
            data[field] = king[field]
    data["execution_price"] = data.get("conservative_price")
    data.update(demo_safety_flags())
    data["blocked_reason"] = "demo_data_never_live"
    data["dry_run"] = True
    data["live_switch"] = False
    data["message_send_attempted"] = False
    data["formal_approval_created"] = False
    data["live_execution_count"] = 0
    return data


def revenue_decision_input() -> dict[str, Any]:
    snapshot = business_snapshot()
    king = room_type("KING")
    market = market_context()
    progress = progress_deviation()
    orders = orders_aggregate()
    data = {
        **demo_safety_flags(),
        **snapshot,
        **orders,
        "room_type_id": king["room_type_id"],
        "room_type_name": king["room_type_name"],
        "current_price": king["current_price"],
        "floor_price": king["floor_price"],
        "ceiling_price": king["ceiling_price"],
        "candidate_price": king["candidate_price"],
        "conservative_price": king["conservative_price"],
        "max_single_change_pct": king["max_single_change_pct"],
        "max_increase_pct": king.get("max_increase_pct", king["max_single_change_pct"]),
        "max_decrease_pct": king.get("max_decrease_pct", king["max_single_change_pct"]),
        "min_increase_pct": king.get("min_increase_pct", 0.0),
        "min_decrease_pct": king.get("min_decrease_pct", 0.0),
        "channel": king["channel"],
        "adapter": king["adapter"],
        "method": king["method"],
        "demand_index": market["demand_index"],
        "demand_level": market["demand_level"],
        "demand_pressure": market["demand_index"] / 100,
        "progress_status": progress["progress_status"],
        "progress_gap": progress["progress_gap"],
        "inventory_pressure": round(king["sold_rooms"] / max(king["inventory"], 1), 4),
        "conversion_problem": False,
        "source_capability": "read_only",
    }
    return data


def external_ota_report_fields() -> dict[str, Any]:
    data = dict(load_demo_fact("external_ota_report_fields.json"))
    data.update(demo_safety_flags())
    return data


def external_ota_field_coverage() -> dict[str, Any]:
    data = external_ota_report_fields()
    coverage = calculate_field_coverage(
        required_fields=data.get("field_coverage_required_fields") or [],
        available_fields=data.get("field_coverage_available_fields") or [],
        partial_fields=data.get("field_coverage_partial_fields") or [],
        missing_fields=data.get("field_coverage_missing_fields") or [],
    )
    coverage["calculation_source"] = data.get("field_contract_source")
    return coverage


def external_ota_report_preview() -> dict[str, Any]:
    data = external_ota_report_fields()
    coverage = external_ota_field_coverage()
    result = {
        **demo_safety_flags(),
        "node_id": "N022",
        "skill_id": "S14-EXT",
        "status": "preview_only",
        "field_coverage_report": coverage,
        "html_report_preview_status": data.get("html_report_preview_status", "structure_only"),
        "html_report_preview_available": bool(data.get("html_report_preview_available")),
        "html_report_preview_note": data.get("html_report_preview_note"),
        "html_report_sections": data.get("html_report_sections") or [],
        "html_report_generated": False,
        "html_report_path": None,
        "canvas_render_status": "not_attempted",
        "fallback_available": True,
        "ota_health_score": data.get("ota_health_score"),
        "hos_score": data.get("hos_score"),
        "psi_score": data.get("psi_score"),
        "content_score": data.get("content_score"),
        "conversion_rate": data.get("conversion_rate"),
        "confirmation_rate": data.get("confirmation_rate"),
        "ranking": data.get("ranking"),
        "exposure_score": data.get("exposure_score"),
    }
    try:
        artifact = generate_external_ota_html_report(result)
        result.update(artifact)
        result["html_report_preview_available"] = True
        result["html_report_generated"] = True
        result["html_report_path"] = artifact.get("artifact_path")
        result["canvas_render_status"] = "not_attempted"
        result["fallback_available"] = True
        result["html_report_preview_note"] = "已由 runtime 生成 HTML 预览文件；仍为 demo_data，不代表今日真实经营。"
    except OSError:
        result["html_report_preview_status"] = "structure_only"
        result["html_report_generated"] = False
        result["html_report_path"] = None
        result["canvas_render_status"] = "failed/fallback_text"
        result["fallback_available"] = True
        result["html_report_preview_note"] = "当前仅输出 HTML 报告结构预览，尚未生成完整 HTML 文件。"
    return result
