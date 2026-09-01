from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "contracts" / "v27" / "contract.json"


def io_field(field_id: str, key: str, zh_name: str, data_type: str, *, direction: str) -> dict[str, Any]:
    return {
        "field_id": field_id,
        "canonical_key": key,
        "project_field_name": key,
        "zh_name": zh_name,
        "data_type": data_type,
        "required_level": "节点输入" if direction == "input" else "节点输出",
        "source_type": "server_resolved" if direction == "input" else "upstream_output",
        "source_node": "" if direction == "input" else "N014",
        "source_skill": "" if direction == "input" else "S17",
        "downstream_node": [] if direction == "input" else ["N015", "N018", "N019"],
        "missing_policy": "缺失时保留对应 population data_gap，不得编造或跨 population 补齐",
        "evidence": "重构算法.md S17 客户订单分析",
    }


def registry_field(field: dict[str, Any], *, direction: str) -> dict[str, Any]:
    field_id = field["field_id"]
    return {
        **field,
        "description": f"{field['zh_name']}；S17 deterministic aggregate contract.",
        "field_group": "S17",
        "field_package": "S17",
        "field_type": "system_context" if direction == "input" else "derived_output",
        "blueprint_ids": ["BP08", "BP09"],
        "blueprint_original_fields": [],
        "algorithm_usage": "S17 customer and order structure analysis",
        "source_layer": "server-resolved context" if direction == "input" else "deterministic aggregate",
        "actual_source_candidates": [],
        "actual_source_aliases": [],
        "source_match_status": "confirmed_exact" if direction == "input" else "algorithm_output",
        "source_match_reason": "MD S17 approved contract",
        "project_schema_evidence": "runtime/adapters/s17_repository.py；runtime/algorithms/customer_order.py",
        "used_by_nodes": ["N014"],
        "used_by_skills": ["S17"],
        "io_direction": direction,
        "upstream_node": "" if direction == "input" else "N014",
        "privacy_level": "restricted" if field_id == "S17I003" else "internal",
        "governance_note": "Different populations remain separate; no customer profile or direct action.",
        "manual_confirm_needed": False,
        "legacy_fix_status": "fixed",
        "legacy_fix_note": "Aligned to MD S17 semantics",
    }


def main() -> None:
    contract = json.loads(PATH.read_text(encoding="utf-8"))
    inputs = [
        io_field("S17I001", "request_context", "S17请求上下文", "object", direction="input"),
        io_field("S17I002", "active_privacy_policy", "S17隐私策略", "object", direction="input"),
        io_field("S17I003", "source_populations", "S17独立来源人口", "object", direction="input"),
    ]
    outputs = [
        io_field("N014_OUT001", "customer_order_populations", "客户与订单独立人口聚合", "object", direction="output"),
        io_field("N014_OUT002", "repeat_booking_contact_share_proxy", "联系人复购代理", "number", direction="output"),
        io_field("N014_OUT003", "provider_loss_proxy", "平台订单流失代理", "object", direction="output"),
        io_field("N014_OUT004", "data_gaps", "S17数据缺口", "array", direction="output"),
    ]
    skill = contract["skills"]["S17"]
    skill.update({
        "skill_name": "客户与订单结构分析",
        "input_fields": inputs,
        "output_fields": outputs,
        "runtime_commands": ["customer-analysis"],
        "acceptance": [
            "exact hotel_id and as-of window are mandatory",
            "populations are not added into a total customer count",
            "contact HMAC and raw order rows never leave the trusted aggregation boundary",
            "proxy metrics are never named verified customer repeat rate",
            "direct_action_allowed=false",
        ],
    })
    node = contract["nodes"]["N014"]
    node.update({
        "node_name": "S17 客户与订单结构分析",
        "direct_trigger": "用户查询订单总览、取消、提前量、入住时长、房型、客源、实现收入或联系人复购代理。",
        "chain_trigger": "经营诊断需要抑制后的酒店级或 canonical 房型级订单结构时触发。",
        "trigger_condition": "需要独立 population 的确定性聚合证据。",
        "process": "exact hotel scope -> latest dedupe -> independent populations -> deterministic metrics -> privacy suppression -> aggregate-only output",
        "runtime": "customer-analysis / database-query customer_order_analysis",
        "delivery": "S17 aggregate-only runtime envelope",
        "acceptance": "不得输出行级订单、联系人或 HMAC；不得生成客户画像、定向优惠或直接动作。",
        "canonical_outputs": [field["canonical_key"] for field in outputs],
        "source_field_basis": "JD01/RS01/KF11/JD04 and independently scoped provider aggregates",
    })
    contract["node_io_contract"]["N014"] = {
        "node_id": "N014",
        "input_field_ids": [field["field_id"] for field in inputs],
        "output_field_ids": [field["field_id"] for field in outputs],
        "inputs": inputs,
        "outputs": outputs,
    }
    contract["skill_io_contract"]["S17"] = {
        "skill_id": "S17",
        "node_ids": ["N014"],
        "agent_ids": ["A1"],
        "blueprint_ids": ["BP08", "BP09"],
        "input_field_ids": [field["field_id"] for field in inputs],
        "output_field_ids": [field["field_id"] for field in outputs],
        "inputs": inputs,
        "outputs": outputs,
        "runtime_commands": ["customer-analysis"],
        "acceptance": skill["acceptance"],
    }
    for field in inputs:
        contract["field_registry"][field["field_id"]] = registry_field(field, direction="input")
    for field in outputs:
        contract["field_registry"][field["field_id"]] = registry_field(field, direction="output")
    PATH.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    references = ROOT / "skills" / "hotel-ota" / "s17-customer-order-analysis" / "references"
    alignment = {
        "skill_id": "S17", "skill_name": "客户与订单结构分析", "node_ids": ["N014"],
        "agent_id": "A1", "agent_ids": ["A1"], "blueprint_basis": ["BP08", "BP09"],
        "input_field_ids": [field["field_id"] for field in inputs],
        "output_field_ids": [field["field_id"] for field in outputs],
        "input_fields": inputs, "output_fields": outputs, "runtime_command": "customer-analysis",
        "demo_data_files": ["examples/demo_data/nodes/N014.json"],
        "error_handling": "population-level data_gap; no synthetic fallback",
        "acceptance_tests": ["tests/test_s17_customer_order_md.py"],
        "schema_version": "v27.0", "source": "contracts/v27/contract.json",
        "field_registry_ref": "contracts/v27/field_registry.yaml",
        "node_io_contract_ref": "contracts/v27/node_io_contract.yaml",
        "legacy_v26_alignment_ref": "references/v26_alignment.json",
        "demo_safety_fields": ["data_source_type=demo_data", "freshness_status=demo_data", "approval_data_allowed=false", "live_allowed=false"],
    }
    (references / "v27_alignment.json").write_text(json.dumps(alignment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    input_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "schema_version": "v27-wrapper",
        "title": "S17 input wrapper", "type": "object", "canonical_source": "contracts/v27/node_io_contract.yaml",
        "secondary_source": "contracts/v27/skill_io_contract.yaml", "alignment_source": "references/v27_alignment.json",
        "skill_id": "S17", "node_ids": ["N014"], "input_field_ids": alignment["input_field_ids"],
        "deprecated_legacy_fields": {"customer_segments": {"deprecated": True}, "repeat_guest_rate": {"deprecated": True}, "review_content": {"deprecated": True}},
        "properties": {field["field_id"]: {"type": field["data_type"], "canonical_key": field["canonical_key"]} for field in inputs},
        "required": alignment["input_field_ids"], "additionalProperties": False,
    }
    output_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "schema_version": "v27-wrapper",
        "title": "S17 output wrapper", "type": "object", "canonical_source": "contracts/v27/node_io_contract.yaml",
        "secondary_source": "contracts/v27/skill_io_contract.yaml", "alignment_source": "references/v27_alignment.json",
        "skill_id": "S17", "node_ids": ["N014"], "output_field_ids": alignment["output_field_ids"],
        "deprecated_legacy_outputs": {"customer_segments": {"deprecated": True}, "repeat_guest_rate": {"deprecated": True}, "target_guest_tasks": {"deprecated": True}},
        "properties": {field["field_id"]: {"type": field["data_type"], "canonical_key": field["canonical_key"]} for field in outputs},
        "required": alignment["output_field_ids"], "additionalProperties": False,
    }
    (references / "input_schema.json").write_text(json.dumps(input_schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (references / "output_schema.json").write_text(json.dumps(output_schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
