from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.validate_v27_contract import CONTRACT_PATH, EXPECTED_AGENT_MAPPING, validate_contract

TMP_DIR = Path(os.environ.get("TMP", "/tmp")) if os.name == "nt" else Path("/tmp")
JSON_OUT = TMP_DIR / "hotel-ota-v27-contract-drift.json"
MD_OUT = TMP_DIR / "hotel-ota-v27-contract-drift.md"

SCAN_TARGETS = [
    "architecture",
    "contracts",
    "router",
    "agents",
    "skills",
    "runtime",
    "examples/demo_data",
    "tests",
    "README.md",
    "AGENTS.md",
    "BOOTSTRAP.md",
    "TOOLS.md",
    "USER.md",
    "IDENTITY.md",
    "SOUL.md",
    "HEARTBEAT.md",
    "MEMORY.md",
]

ALLOWED_LEGACY_PATH_PARTS = {
    "contracts/v26/",
    "docs/architecture_reference/v26/",
    "runtime/v26_",
    "tools/generate_v26_contracts.py",
    "tools/audit_v26_contract_drift.py",
    "tools/sync_v26_docs_and_skills.py",
    "references/v26_alignment.json",
    "test_v26_",
    "v26-alignment-policy.md",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def finding(kind: str, severity: str, path: str, message: str) -> dict[str, str]:
    return {"kind": kind, "severity": severity, "path": path, "message": message}


def iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for target in SCAN_TARGETS:
        path = ROOT / target
        if not path.exists():
            continue
        if path.is_file():
            files.append(path)
        else:
            files.extend(item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in {".py", ".json", ".yaml", ".yml", ".md"})
    return sorted(set(files))


def is_allowed_legacy_path(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    return any(part in normalized for part in ALLOWED_LEGACY_PATH_PARTS)


def audit_contract(findings: list[dict[str, str]]) -> dict[str, Any] | None:
    if not CONTRACT_PATH.exists():
        findings.append(finding("contract", "P0_blocker", "contracts/v27/contract.json", "missing current V27 machine contract"))
        return None
    contract = load_json(CONTRACT_PATH)
    for error in validate_contract(contract):
        findings.append(finding("contract", "P0_blocker", "contracts/v27/contract.json", error))
    return contract


def audit_architecture(contract: dict[str, Any], findings: list[dict[str, str]]) -> None:
    expected_nodes = {f"N{index:03d}" for index in range(1, 23)}
    expected_edges = {f"E{index:03d}" for index in range(1, 68)}
    nodes = load_json(ROOT / "architecture" / "node_registry.json")["nodes"]
    edges = load_json(ROOT / "architecture" / "edge_registry.json")["edges"]
    scenarios = load_json(ROOT / "architecture" / "scenario_chain_registry.json")["scenarios"]
    mapping = load_json(ROOT / "architecture" / "node_agent_mapping.json")["mappings"]
    node_ids = {node.get("node_id") or node.get("id") for node in nodes}
    edge_ids = {edge.get("edge_id") for edge in edges}
    if node_ids != expected_nodes:
        findings.append(finding("architecture", "P0_blocker", "architecture/node_registry.json", "node registry must cover N001-N022"))
    if edge_ids != expected_edges:
        findings.append(finding("architecture", "P0_blocker", "architecture/edge_registry.json", "edge registry must cover E001-E067"))
    if {scenario.get("scenario_id") or scenario.get("id") for scenario in scenarios} != {f"SC{index:02d}" for index in range(1, 11)}:
        findings.append(finding("architecture", "P0_blocker", "architecture/scenario_chain_registry.json", "scenario registry must cover SC01-SC10"))
    expected_by_node = {node_id: agent for agent, nodes_for_agent in EXPECTED_AGENT_MAPPING.items() for node_id in nodes_for_agent}
    for item in mapping:
        if item.get("agent_id") != expected_by_node.get(item.get("node_id")):
            findings.append(finding("agent_mapping", "P0_blocker", "architecture/node_agent_mapping.json", f"{item.get('node_id')} agent mismatch"))


def audit_demo_data(findings: list[dict[str, str]]) -> None:
    demo_dir = ROOT / "examples" / "demo_data"
    missing_nodes = [f"N{index:03d}" for index in range(1, 23) if not (demo_dir / "nodes" / f"N{index:03d}.json").exists()]
    missing_scenarios = [f"SC{index:02d}" for index in range(1, 11) if not (demo_dir / "scenarios" / f"SC{index:02d}.json").exists()]
    if missing_nodes:
        findings.append(finding("demo_data", "P0_blocker", "examples/demo_data/nodes", f"missing demo nodes: {', '.join(missing_nodes)}"))
    if missing_scenarios:
        findings.append(finding("demo_data", "P0_blocker", "examples/demo_data/scenarios", f"missing demo scenarios: {', '.join(missing_scenarios)}"))
    covered: set[str] = set()
    for path in sorted((demo_dir / "scenarios").glob("SC*.json")):
        payload = load_json(path)
        if payload.get("placeholder") is True:
            findings.append(finding("demo_data", "P0_blocker", str(path.relative_to(ROOT)), "scenario fixture is placeholder"))
        covered.update(str(node) for node in payload.get("nodes", []))
    expected_nodes = {f"N{index:03d}" for index in range(1, 23)}
    if not expected_nodes.issubset(covered):
        findings.append(finding("demo_data", "P0_blocker", "examples/demo_data/scenarios", f"scenario fixtures do not cover nodes: {sorted(expected_nodes - covered)}"))


def audit_text_drift(findings: list[dict[str, str]], strict_docs: bool) -> None:
    bad_current_patterns = [
        r"以 V26 为准",
        r"V26 .*最高事实源",
        r"contracts/v26/.*为准",
        r"docs/architecture_reference/v26/.*为准",
    ]
    for path in iter_scan_files():
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        if is_allowed_legacy_path(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in bad_current_patterns:
            if re.search(pattern, text):
                findings.append(finding("legacy_current_source", "P1_must_fix", rel, f"current-source V26 wording found: {pattern}"))
        if rel in {"README.md", "AGENTS.md", "BOOTSTRAP.md", "TOOLS.md", "MEMORY.md"} and "contracts/v27/contract.json" not in text:
            findings.append(finding("docs", "P1_must_fix", rel, "root doc must mention contracts/v27/contract.json"))
        if rel == "contracts/v27/contract.json":
            continue
        if rel.startswith("contracts/") and rel.endswith((".yaml", ".json")) and "contracts/v27/contract.json" not in text and not rel.startswith("contracts/v26/"):
            findings.append(finding("contract_metadata", "P1_must_fix", rel, "contract artifact must reference V27 machine contract"))


def write_reports(findings: list[dict[str, str]]) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    blocking = [item for item in findings if item["severity"] in {"P0_blocker", "P1_must_fix"}]
    payload = {
        "status": "ok" if not blocking else "failed",
        "finding_count": len(findings),
        "blocking_count": len(blocking),
        "p0_count": sum(1 for item in findings if item["severity"] == "P0_blocker"),
        "p1_count": sum(1 for item in findings if item["severity"] == "P1_must_fix"),
        "findings": findings,
    }
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# V27 Contract Drift Audit", "", f"- status: {payload['status']}", f"- findings: {payload['finding_count']}", f"- P0: {payload['p0_count']}", f"- P1: {payload['p1_count']}", ""]
    for item in findings:
        lines.append(f"- [{item['severity']}] {item['kind']} `{item['path']}`: {item['message']}")
    MD_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-docs", action="store_true")
    args = parser.parse_args(argv)
    findings: list[dict[str, str]] = []
    contract = audit_contract(findings)
    if contract:
        audit_architecture(contract, findings)
    audit_demo_data(findings)
    audit_text_drift(findings, args.strict_docs)
    write_reports(findings)
    blocking = [item for item in findings if item["severity"] in {"P0_blocker", "P1_must_fix"}]
    print(json.dumps({"status": "ok" if not blocking else "failed", "P0": sum(1 for item in findings if item["severity"] == "P0_blocker"), "P1": sum(1 for item in findings if item["severity"] == "P1_must_fix"), "json": str(JSON_OUT), "md": str(MD_OUT)}, ensure_ascii=False))
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
