from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "v27" / "contract.json"
V27_DIR = ROOT / "contracts" / "v27"
CONTRACT_DIR = ROOT / "contracts"
ARCH_DIR = ROOT / "architecture"
SOURCE_MANIFEST = ROOT / "references" / "source" / "source_manifest.yaml"


def load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def values(section: Any) -> list[dict[str, Any]]:
    if isinstance(section, dict):
        return [dict(item) for item in section.values() if isinstance(item, dict)]
    if isinstance(section, list):
        return [dict(item) for item in section if isinstance(item, dict)]
    return []


def clean_text(text: str) -> str:
    return (
        text.replace("V25字段契约字段级展开", "V27字段契约字段级展开")
        .replace("字段契约以 V25 为准", "字段契约以 V27 为当前工程契约")
        .replace("V26 nodes", "V27 nodes")
        .replace("V26", "legacy V26")
    )


def clean_obj(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: clean_obj(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_obj(item) for item in value]
    if isinstance(value, str):
        return clean_text(value)
    return value


def field_registry(contract: dict[str, Any]) -> dict[str, Any]:
    fields = clean_obj(values(contract["field_registry"]))
    governance = contract["field_governance_policy"]
    validation = contract["validation_rules"]
    return {
        "schema_version": "v27.0",
        "source_version": contract["metadata"]["contract_version"],
        "machine_contract": "contracts/v27/contract.json",
        "compatibility_note": "Top-level compatibility contracts mirror V27. contracts/v26 is legacy migration reference only.",
        "field_count": len(fields),
        "status_policy": {
            "supported_statuses": list(governance["status_definitions"].keys()),
            "legacy_values_are_not_current_contract": True,
        },
        "supported_statuses": list(governance["status_definitions"].keys()),
        "supported_data_types": validation["allowed_data_types"],
        "algorithm_field_requirements": clean_obj(values(contract.get("algorithm_field_requirements"))),
        "fields": fields,
    }


def node_io(contract: dict[str, Any]) -> dict[str, Any]:
    nodes = []
    node_contract = contract["node_io_contract"]
    for node in values(contract["nodes"]):
        node_id = node["node_id"]
        io = dict(node_contract[node_id])
        nodes.append(
            clean_obj(
                {
                    "node_id": node_id,
                    "node_name": node.get("node_name"),
                    "skill_id": node.get("skill_id"),
                    "agent_id": node.get("agent_id"),
                    "input_field_ids": io.get("input_field_ids") or [],
                    "output_field_ids": io.get("output_field_ids") or [],
                    "input_fields": io.get("inputs") or [],
                    "output_fields": io.get("outputs") or [],
                    "direct_trigger": node.get("direct_trigger"),
                    "chain_trigger": node.get("chain_trigger"),
                    "trigger_condition": node.get("trigger_condition"),
                    "upstream_nodes": node.get("upstream_nodes") or [],
                    "downstream_nodes": node.get("downstream") or [],
                    "edge_payloads": [],
                    "blueprint_basis": node.get("blueprint_ids") or [],
                    "acceptance": node.get("acceptance"),
                }
            )
        )
    return {
        "schema_version": "v27.0",
        "source_version": contract["metadata"]["contract_version"],
        "machine_contract": "contracts/v27/contract.json",
        "nodes": nodes,
    }


def skill_io(contract: dict[str, Any]) -> dict[str, Any]:
    skills = []
    skill_contract = contract["skill_io_contract"]
    for skill in values(contract["skills"]):
        skill_id = skill["skill_id"]
        io = dict(skill_contract[skill_id])
        node_ids = io.get("node_ids") or skill.get("node_ids") or []
        demo_node = node_ids[0] if node_ids else "N000"
        skills.append(
            clean_obj(
                {
                    "skill_id": skill_id,
                    "skill_name": skill.get("skill_name") or skill_id,
                    "node_ids": node_ids,
                    "agent_id": (io.get("agent_ids") or skill.get("agent_ids") or [""])[0],
                    "agent_ids": io.get("agent_ids") or skill.get("agent_ids") or [],
                    "blueprint_basis": io.get("blueprint_ids") or skill.get("blueprint_ids") or [],
                    "input_field_ids": io.get("input_field_ids") or [],
                    "output_field_ids": io.get("output_field_ids") or [],
                    "input_fields": io.get("inputs") or [],
                    "output_fields": io.get("outputs") or [],
                    "runtime_command": skill.get("runtime_command") or "",
                    "demo_data_files": ["examples/demo_data/demo_manifest.json", f"examples/demo_data/nodes/{demo_node}.json"],
                    "error_handling": skill.get("error_handling") or "",
                    "acceptance_tests": ["tests/contracts/test_v27_skill_io_contract.py"],
                }
            )
        )
    return {
        "schema_version": "v27.0",
        "source_version": contract["metadata"]["contract_version"],
        "machine_contract": "contracts/v27/contract.json",
        "core_skill_count": 17,
        "extension_skill_count": 1,
        "skills": skills,
    }


def edge_payload(contract: dict[str, Any]) -> dict[str, Any]:
    edges = []
    for edge in values(contract["edges"]):
        payload = contract["edge_payload_contract"].get(edge["edge_id"], {})
        edges.append(
            clean_obj(
                {
                    "edge_id": edge["edge_id"],
                    "source_node_id": edge.get("source_node_id"),
                    "target_node_id": edge.get("target_node_id"),
                    "trigger_type": edge.get("trigger_type"),
                    "why": edge.get("why"),
                    "payload": edge.get("payload_summary"),
                    "source_outputs": payload.get("source_outputs") or [],
                    "target_inputs": payload.get("target_inputs") or [],
                    "mapping_rows": payload.get("mapping_rows") or [],
                    "blueprint": edge.get("blueprint_ids") or [],
                    "source_output_mapping_required": True,
                    "target_input_mapping_required": True,
                }
            )
        )
    return {"schema_version": "v27.0", "edge_count": len(edges), "machine_contract": "contracts/v27/contract.json", "edges": edges}


def scenario_chain(contract: dict[str, Any]) -> dict[str, Any]:
    scenarios = []
    for scenario in values(contract["scenarios"]):
        scenario_id = scenario["scenario_id"]
        scenarios.append(
            clean_obj(
                {
                    "id": scenario_id,
                    "scenario_id": scenario_id,
                    "name": scenario.get("scenario_name"),
                    "trigger": scenario.get("trigger"),
                    "nodes": scenario.get("node_chain") or [],
                    "skills": scenario.get("skill_chain") or [],
                    "agents": scenario.get("agent_plan") or [],
                    "required_edges": scenario.get("required_edges") or [],
                    "optional_edges": scenario.get("optional_edges") or [],
                    "forbidden_edges": [],
                    "stages": scenario.get("stages") or [],
                    "demo_supported": True,
                    "demo_fixture_id": scenario_id,
                    "demo_expected_outputs": [
                        "data_source_type=demo_data",
                        "freshness_status=demo_data",
                        "approval_data_allowed=false",
                        "live_allowed=false",
                    ],
                    "demo_policy": scenario.get("demo_policy") or {},
                }
            )
        )
    return {
        "schema_version": "v27.0",
        "source_version": contract["metadata"]["contract_version"],
        "machine_contract": "contracts/v27/contract.json",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }


def source_alias(contract: dict[str, Any]) -> dict[str, Any]:
    aliases = clean_obj(contract["source_alias_mapping"])
    inventory = clean_obj(contract["source_field_inventory"])
    return {
        "schema_version": "v27.0",
        "source_version": contract["metadata"]["contract_version"],
        "machine_contract": "contracts/v27/contract.json",
        "private_values_allowed": False,
        "source_field_count": len(inventory),
        "aliases": aliases,
        "source_field_inventory": inventory,
    }


def architecture_payloads(contract: dict[str, Any]) -> dict[str, Any]:
    nodes = []
    for node in values(contract["nodes"]):
        nodes.append(
            clean_obj(
                {
                    "id": node["node_id"],
                    "node_id": node["node_id"],
                    "name": node.get("node_name"),
                    "skill_id": node.get("skill_id"),
                    "agent_id": node.get("agent_id"),
                    "phase": node.get("phase"),
                    "module": node.get("module"),
                    "layer": node.get("layer"),
                    "blueprint": node.get("blueprint_ids") or [],
                    "direct_trigger": node.get("direct_trigger"),
                    "chain_trigger": node.get("chain_trigger"),
                    "trigger_condition": node.get("trigger_condition"),
                    "inputs": [field.get("canonical_key") for field in node.get("inputs", [])],
                    "outputs": [field.get("canonical_key") for field in node.get("outputs", [])],
                    "downstream": node.get("downstream") or [],
                    "runtime": node.get("runtime"),
                    "delivery": node.get("delivery"),
                    "acceptance": node.get("acceptance"),
                }
            )
        )
    edges = clean_obj(values(contract["edges"]))
    scenarios = scenario_chain(contract)["scenarios"]
    agents = clean_obj(values(contract["agents"]))
    mappings = [
        {
            "node_id": node["node_id"],
            "node_name": node.get("node_name"),
            "agent_id": node.get("agent_id"),
            "skill_id": node.get("skill_id"),
            "source": "contracts/v27/contract.json",
        }
        for node in values(contract["nodes"])
    ]
    source_version = contract["metadata"]["contract_version"]
    return {
        "node_registry.json": {"schema_version": "v27.0", "source_version": source_version, "machine_contract": "contracts/v27/contract.json", "nodes": nodes},
        "edge_registry.json": {"schema_version": "v27.0", "source_version": source_version, "machine_contract": "contracts/v27/contract.json", "edges": edges},
        "scenario_chain_registry.json": {"schema_version": "v27.0", "source_version": source_version, "machine_contract": "contracts/v27/contract.json", "scenarios": scenarios},
        "agent_registry.json": {"schema_version": "v27.0", "source_version": source_version, "machine_contract": "contracts/v27/contract.json", "agents": agents},
        "node_agent_mapping.json": {"schema_version": "v27.0", "source_version": source_version, "machine_contract": "contracts/v27/contract.json", "mappings": mappings},
    }


def source_manifest(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "v27.0",
        "current_machine_contract": "contracts/v27/contract.json",
        "source_version": contract["metadata"]["contract_version"],
        "source_priority": contract.get("source_priority") or [],
        "current_fact_policy": [
            "contracts/v27/contract.json is the only current machine-readable engineering contract.",
            "docs/architecture_reference/v27/酒店OTA_AI数字员工_协作开发总地图_V27_项目修复可执行契约版.json is the archived V27 source copy.",
            "docs/architecture_reference/v27/数据列表.txt is an archived V27 source-candidate supplement, not a higher authority than contract.json.",
            "contracts/v26 and docs/architecture_reference/v26 are legacy migration references only.",
            "Current project evidence may not reverse-define fields, nodes, edges, scenarios, or demo outputs.",
        ],
        "derived_artifacts": [
            "contracts/v27/field_registry.yaml",
            "contracts/v27/node_io_contract.yaml",
            "contracts/v27/skill_io_contract.yaml",
            "contracts/v27/edge_payload_contract.yaml",
            "contracts/v27/scenario_chain_contract.yaml",
            "contracts/v27/source_alias_mapping.yaml",
            "contracts/v27/field_governance_policy.yaml",
            "architecture/node_registry.json",
            "architecture/edge_registry.json",
            "architecture/scenario_chain_registry.json",
            "architecture/agent_registry.json",
            "architecture/node_agent_mapping.json",
        ],
        "source_archives": {
            "v27_contract_source": "docs/architecture_reference/v27/酒店OTA_AI数字员工_协作开发总地图_V27_项目修复可执行契约版.json",
            "v27_source_field_reference": "docs/architecture_reference/v27/整体架构分析(1).xlsx",
            "v27_source_data_list": "docs/architecture_reference/v27/数据列表.txt",
            "v26_legacy_reference_dir": "docs/architecture_reference/v26",
            "external_not_archived": [],
        },
        "legacy_references": {
            "contracts/v26": "legacy migration reference, not current source of truth",
            "docs/architecture_reference/v26": "legacy collaboration archive",
        },
    }


def main() -> int:
    contract = load_contract()
    dump(V27_DIR / "field_registry.yaml", field_registry(contract))
    dump(V27_DIR / "node_io_contract.yaml", node_io(contract))
    dump(V27_DIR / "skill_io_contract.yaml", skill_io(contract))
    dump(V27_DIR / "edge_payload_contract.yaml", edge_payload(contract))
    dump(V27_DIR / "scenario_chain_contract.yaml", scenario_chain(contract))
    dump(V27_DIR / "source_alias_mapping.yaml", source_alias(contract))
    dump(
        V27_DIR / "field_governance_policy.yaml",
        {
            "schema_version": "v27.0",
            "source_version": contract["metadata"]["contract_version"],
            "machine_contract": "contracts/v27/contract.json",
            "policy": clean_obj(contract["field_governance_policy"]),
        },
    )
    dump(CONTRACT_DIR / "field_registry.yaml", field_registry(contract))
    dump(CONTRACT_DIR / "node_io_contract.yaml", node_io(contract))
    dump(CONTRACT_DIR / "source_mapping.yaml", source_alias(contract))
    dump(
        CONTRACT_DIR / "contract_version.yaml",
        {
            "schema_version": "v27.0",
            "current_machine_contract": "contracts/v27/contract.json",
            "source_version": contract["metadata"]["contract_version"],
            "compatibility_note": "Top-level contract files mirror contracts/v27. contracts/v26 is legacy migration reference only.",
        },
    )
    for filename, payload in architecture_payloads(contract).items():
        dump(ARCH_DIR / filename, payload)
    dump(SOURCE_MANIFEST, source_manifest(contract))
    print(
        json.dumps(
            {
                "status": "ok",
                "source_version": contract["metadata"]["contract_version"],
                "fields": len(contract["field_registry"]),
                "nodes": len(contract["nodes"]),
                "edges": len(contract["edges"]),
                "scenarios": len(contract["scenarios"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
