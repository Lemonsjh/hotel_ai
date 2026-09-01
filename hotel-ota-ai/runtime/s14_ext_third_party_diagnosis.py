from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.demo_facts import demo_safety_flags, external_ota_report_fields
from runtime.field_coverage import calculate_field_coverage
from runtime.reports.external_ota_html_report import generate_external_ota_html_report
from runtime.s14_operation_diagnosis import diagnose_s14_excel_file, diagnose_s14_mysql_template_result


S14_EXT_FORMULA_VERSION = "s14_ext_v4_41_rules_c01_c07_from_s14_feishu_test_zip"
S14_EXT_MODULE_IDS = [f"M0{index}" for index in range(1, 9)]


def _base_external_result(*, hotel_id: str, source_mode: str) -> dict[str, Any]:
    safety = demo_safety_flags()
    return {
        **safety,
        "node_id": "N022",
        "skill_id": "S14-EXT",
        "source_mode": source_mode,
        "external_isolated": True,
        "requires_hotel_tenant_auth": False,
        "formula_version": S14_EXT_FORMULA_VERSION,
        "source_package": "s14-feishu-test.zip",
        "source_package_ingest_policy": "selected_runtime_calculator_reader_template_only",
        "module_ids": S14_EXT_MODULE_IDS,
        "rule_count": 41,
        "cap_rule_ids": [f"C0{index}" for index in range(1, 8)],
        "hotel_id": hotel_id or safety.get("hotel_id"),
        "approval_data_allowed": False,
        "formal_approval_allowed": False,
        "formal_approval_created": False,
        "live_allowed": False,
        "live_execution_count": 0,
    }


def _strip_local_artifact_keys(result: dict[str, Any]) -> dict[str, Any]:
    # Feishu and demo-chain payloads should never expose filesystem artifacts.
    if result.get("artifact_path"):
        result["html_artifact_metadata"] = {
            "report_id": result.get("report_id"),
            "artifact_type": result.get("artifact_type"),
            "section_count": result.get("section_count"),
            "generated_by_runtime": result.get("generated_by_runtime"),
        }
    result.pop("artifact_path", None)
    result.pop("report_local_path", None)
    result["html_report_path"] = None
    return result


def build_s14_ext_third_party_preview(
    *,
    hotel_id: str = "third-party-demo",
    raw_fields: dict[str, Any] | None = None,
    generate_html: bool = True,
    expose_local_path: bool = False,
) -> dict[str, Any]:
    fields = dict(raw_fields or external_ota_report_fields())
    required = fields.get("field_coverage_required_fields") or []
    available = fields.get("field_coverage_available_fields") or []
    partial = fields.get("field_coverage_partial_fields") or []
    missing = fields.get("field_coverage_missing_fields") or []
    coverage = calculate_field_coverage(
        required_fields=required,
        available_fields=available,
        partial_fields=partial,
        missing_fields=missing,
    )
    coverage["calculation_source"] = fields.get("field_contract_source") or "s14_ext_third_party_contract"

    result = {
        **_base_external_result(hotel_id=hotel_id, source_mode="third_party_demo"),
        "status": "preview_only",
        "field_coverage_report": coverage,
        "field_coverage_rate": coverage.get("field_coverage_rate"),
        "missing_fields": missing,
        "html_report_preview_status": "structure_only",
        "html_report_preview_available": False,
        "html_report_generated": False,
        "html_report_path": None,
        "report_url": None,
        "publisher_status": "not_configured",
        "canvas_render_status": "not_attempted",
        "fallback_available": True,
        "ota_health_score": fields.get("ota_health_score"),
        "hos_score": fields.get("hos_score"),
        "psi_score": fields.get("psi_score"),
        "content_score": fields.get("content_score"),
        "conversion_rate": fields.get("conversion_rate"),
        "confirmation_rate": fields.get("confirmation_rate"),
        "ranking": fields.get("ranking"),
        "exposure_score": fields.get("exposure_score"),
        "module_scores": [
            {
                "module_id": module_id,
                "name": module_id,
                "score": None,
                "weight": None,
                "confidence": "structure_only",
            }
            for module_id in S14_EXT_MODULE_IDS
        ],
        "risk_flags": ["third_party_report_preview_only", "external_isolated_no_live"],
        "not_allowed_conclusions": [
            "cannot_use_external_preview_as_current_hotel_fact",
            "cannot_create_formal_approval_from_s14_ext",
            "cannot_trigger_live_action_from_s14_ext",
        ],
    }
    if generate_html:
        try:
            artifact = generate_external_ota_html_report(result)
            result.update(artifact)
            result["html_report_generated"] = True
            result["html_report_path"] = artifact.get("artifact_path")
            result["html_report_preview_available"] = True
        except OSError:
            result["canvas_render_status"] = "failed/fallback_text"
            result["fallback_available"] = True
    if not expose_local_path:
        _strip_local_artifact_keys(result)
    return result


def diagnose_s14_ext_excel_file(path: str, *, hotel_id: str, report_dir: str | None = None) -> dict[str, Any]:
    # Reuse the bounded reader/calculator extracted from the S14 package, but
    # project the result onto the isolated S14-EXT contract identity.
    result = diagnose_s14_excel_file(path, hotel_id=hotel_id, report_dir=report_dir)
    existing_report_url = result.get("report_url")
    existing_publisher_status = result.get("publisher_status")
    result.update(_base_external_result(hotel_id=hotel_id, source_mode="third_party_excel"))
    result["contract_skill_id"] = "S14-EXT"
    result["html_report_preview_status"] = result.get("html_report_preview_status", "structure_only")
    result["report_url"] = existing_report_url
    result["publisher_status"] = existing_publisher_status or result.get("publisher_status") or "not_configured"
    if not report_dir:
        _strip_local_artifact_keys(result)
    return result


def diagnose_s14_ext_mysql_template_result(
    template_result: dict[str, Any],
    *,
    hotel_id: str,
    report_dir: str | None = None,
) -> dict[str, Any]:
    result = diagnose_s14_mysql_template_result(template_result, hotel_id=hotel_id, report_dir=report_dir)
    existing_report_url = result.get("report_url")
    existing_publisher_status = result.get("publisher_status")
    result.update(_base_external_result(hotel_id=hotel_id, source_mode="third_party_mysql"))
    result["contract_skill_id"] = "S14-EXT"
    result["html_report_preview_status"] = result.get("html_report_preview_status", "structure_only")
    result["report_url"] = existing_report_url
    result["publisher_status"] = existing_publisher_status or result.get("publisher_status") or "not_configured"
    if not report_dir:
        _strip_local_artifact_keys(result)
    return result


def safe_report_dir(path: str | None) -> str | None:
    if not path:
        return None
    return str(Path(path))
