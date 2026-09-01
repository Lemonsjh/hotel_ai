from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTICE = """## V26 Registry-First Notice

当前项目曾经过 V19/V20/V22/V25 阶段迁移；现阶段以 V26 为准。
字段、节点、Agent、边、场景链路和 demo 输出的最高事实源是 `docs/architecture_reference/v26/`、`architecture/` 与 `contracts/v26/`。
当前文档仅作为兼容说明或历史上下文；如与 V26 registry/contract/runtime 冲突，以 V26 为准。

"""


def update_text_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace("V20 Registry-First Notice", "V26 Registry-First Notice")
    text = text.replace("V20 registries", "V26 registries")
    text = text.replace("V20 registry", "V26 registry")
    if "V26 Registry-First Notice" not in text:
        text = NOTICE + text
    path.write_text(text, encoding="utf-8")


def update_requirement_docs() -> None:
    index_path = ROOT / "architecture" / "phase9_document_convergence_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["schema_version"] = "v26.0"
    index["phase"] = "Phase 9 / V26 convergence"
    index["authoritative_order"] = [
        "docs/architecture_reference/v26 as source archive",
        "contracts/v26 for field, node IO, Skill IO, edge payload, and scenario chain contracts",
        "architecture registries generated from V26",
        "runtime safety modules for auth/approval/freshness/live/demo",
        "router for scenario routing",
        "skill references for per-skill behavior",
        "requirements documents as retained compatibility context",
    ]
    for doc in index.get("documents", []):
        path = ROOT / doc["path"]
        if path.exists():
            update_text_file(path)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for rel in [
        "architecture/phase9_document_convergence.md",
        "architecture/implementation_status.md",
        "architecture/algorithm_coverage_matrix.md",
        "architecture/p0p1_delivery_scope.md",
    ]:
        path = ROOT / rel
        if path.exists():
            update_text_file(path)


def update_skill_docs() -> None:
    skill_contract = json.loads((ROOT / "contracts" / "v26" / "skill_io_contract.yaml").read_text(encoding="utf-8"))
    by_id = {skill["skill_id"]: skill for skill in skill_contract["skills"]}
    for skill_dir in (ROOT / "skills" / "hotel-ota").glob("s*"):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        rules_md = skill_dir / "references" / "rules.md"
        if skill_md.exists():
            text = skill_md.read_text(encoding="utf-8")
            text = text.replace("## V20 架构绑定", "## V26 架构绑定")
            text = text.replace("V20 alignment", "V26 alignment")
            text = text.replace("V20 对齐", "V26 对齐")
            text = text.replace("references/v20_alignment.json", "references/v26_alignment.json")
            skill_md.write_text(text, encoding="utf-8")
        if rules_md.exists():
            text = rules_md.read_text(encoding="utf-8")
            text = text.replace("V20 可施工算法规格", "V26 可施工算法规格")
            if "V26 可施工算法规格" not in text:
                text += "\n\n## V26 可施工算法规格\n\n字段与 IO 以 `contracts/v26/` 为准；demo_data 仅可 preview/dry-run，不能正式审批或 live。\n"
            rules_md.write_text(text, encoding="utf-8")

        existing = list((skill_dir / "references").glob("v20_alignment.json"))
        skill_id = None
        existing_data = {}
        if existing:
            try:
                existing_data = json.loads(existing[0].read_text(encoding="utf-8"))
                skill_id = existing_data.get("skill_id")
            except json.JSONDecodeError:
                skill_id = None
        if not skill_id:
            for candidate, contract in by_id.items():
                if contract.get("english_dir_name") and str(contract["english_dir_name"]) in skill_dir.name:
                    skill_id = candidate
                    break
        if skill_id and skill_id in by_id:
            payload = {
                "schema_version": "v26.0",
                "source": "contracts/v26/skill_io_contract.yaml",
                **by_id[skill_id],
                "node_registry_ref": "architecture/node_registry.json",
                "edge_registry_ref": "architecture/edge_registry.json",
                "scenario_registry_ref": "architecture/scenario_chain_registry.json",
                "field_registry_ref": "contracts/v26/field_registry.yaml",
                "node_io_contract_ref": "contracts/v26/node_io_contract.yaml",
                "algorithm_rules_ref": existing_data.get("algorithm_rules_ref") or "runtime/algorithm_rules/demo_rules.yaml",
                "demo_node_fixture": existing_data.get("demo_node_fixture") or f"examples/demo_data/nodes/{(by_id[skill_id]['node_ids'] or ['N000'])[0]}.json",
                "forbidden_actions": existing_data.get("forbidden_actions")
                or [
                    "treat_demo_data_as_real_today_data",
                    "create_formal_approval_from_demo_data",
                    "live_execute_from_demo_data",
                ],
                "demo_safety": {
                    "data_source_type": "demo_data",
                    "approval_data_allowed": False,
                    "live_allowed": False,
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                },
            }
            (skill_dir / "references" / "v26_alignment.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_algorithm_rule_refs() -> None:
    for path in (ROOT / "runtime" / "algorithm_rules").glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        text = text.replace("references/v20_alignment.json", "references/v26_alignment.json")
        text = text.replace("v20_alignment.json", "v26_alignment.json")
        path.write_text(text, encoding="utf-8")
    for rel in [
        "architecture/algorithm_coverage_matrix.md",
        "architecture/redundancy_conflict_missing_audit.md",
    ]:
        path = ROOT / rel
        if path.exists():
            text = path.read_text(encoding="utf-8")
            text = text.replace("references/v20_alignment.json", "references/v26_alignment.json")
            text = text.replace("v20_alignment.json", "v26_alignment.json")
            path.write_text(text, encoding="utf-8")
    shared_v20 = ROOT / "skills" / "hotel-ota" / "_shared" / "v20-alignment-policy.md"
    shared_v26 = ROOT / "skills" / "hotel-ota" / "_shared" / "v26-alignment-policy.md"
    if shared_v20.exists():
        text = shared_v20.read_text(encoding="utf-8")
        text = text.replace("V20", "V26").replace("v20_alignment.json", "v26_alignment.json")
        shared_v26.write_text(text, encoding="utf-8")


def main() -> int:
    update_requirement_docs()
    update_skill_docs()
    update_algorithm_rule_refs()
    print(json.dumps({"status": "ok", "updated": ["requirements", "architecture docs", "skill docs", "algorithm rules"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
