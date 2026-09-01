from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = Path("/tmp")
if os.name == "nt":
    TMP_DIR = Path(os.environ.get("TMP", str(TMP_DIR)))

JSON_OUT = TMP_DIR / "hotel-ota-v26-contract-drift.json"
MD_OUT = TMP_DIR / "hotel-ota-v26-contract-drift.md"

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

BAD_DOC_VERSION_PATTERNS = ["V19_v9_main_route_edge_density", "字段契约_V22", "V20 Registry"]
BAD_STATUS_VALUES = {"fixed", "to_confirm", "inferred_alias"}
EXPECTED_AGENT_MAPPING = {
    "N001": "A0",
    "N002": "A0",
    "N003": "A0",
    "N004": "A0",
    "N005": "A1",
    "N006": "A1",
    "N007": "A1",
    "N008": "A1",
    "N009": "A2",
    "N010": "A2",
    "N011": "A2",
    "N012": "A3",
    "N013": "A3",
    "N014": "A1",
    "N015": "A3",
    "N016": "A4",
    "N017": "A4",
    "N018": "A5",
    "N019": "A6",
    "N020": "A1",
    "N021": "A4",
    "N022": "A2",
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


def audit_field_registry(findings: list[dict[str, str]]) -> set[str]:
    registry = load_json(ROOT / "contracts" / "v26" / "field_registry.yaml")
    keys: set[str] = set()
    ids: set[str] = set()
    allowed_statuses = set(registry["supported_statuses"])
    allowed_types = set(registry["supported_data_types"])
    for field in registry.get("fields", []):
        field_id = str(field.get("field_id") or "")
        key = str(field.get("canonical_key") or "")
        if not field_id or field_id in ids:
            findings.append(finding("field_registry", "error", "contracts/v26/field_registry.yaml", f"duplicate or missing field_id: {field_id}"))
        ids.add(field_id)
        if not key or key in keys:
            findings.append(finding("field_registry", "error", "contracts/v26/field_registry.yaml", f"duplicate or missing canonical_key: {key}"))
        keys.add(key)
        if key and not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            findings.append(finding("field_registry", "error", "contracts/v26/field_registry.yaml", f"not snake_case: {key}"))
        if field.get("source_match_status") not in allowed_statuses:
            findings.append(finding("field_registry", "error", "contracts/v26/field_registry.yaml", f"{field_id} unsupported status {field.get('source_match_status')}"))
        if field.get("data_type") not in allowed_types:
            findings.append(finding("field_registry", "error", "contracts/v26/field_registry.yaml", f"{field_id} unsupported data_type {field.get('data_type')}"))
        if "待命名字段" in json.dumps(field, ensure_ascii=False) or "字段覆盖率率" in json.dumps(field, ensure_ascii=False):
            findings.append(finding("field_registry", "error", "contracts/v26/field_registry.yaml", f"{field_id} unresolved naming marker"))
    return keys


def audit_node_io(field_keys: set[str], findings: list[dict[str, str]]) -> None:
    node_io = load_json(ROOT / "contracts" / "v26" / "node_io_contract.yaml")
    nodes = {node["node_id"]: node for node in node_io.get("nodes", [])}
    for node_id in [f"N{index:03d}" for index in range(1, 23)]:
        node = nodes.get(node_id)
        if not node:
            findings.append(finding("node_io", "error", "contracts/v26/node_io_contract.yaml", f"missing node {node_id}"))
            continue
        if not node.get("input_fields"):
            findings.append(finding("node_io", "error", "contracts/v26/node_io_contract.yaml", f"{node_id} input_fields missing"))
        if not node.get("output_fields"):
            findings.append(finding("node_io", "error", "contracts/v26/node_io_contract.yaml", f"{node_id} output_fields missing"))
        if node.get("agent_id") != EXPECTED_AGENT_MAPPING[node_id]:
            findings.append(finding("agent_mapping", "error", "contracts/v26/node_io_contract.yaml", f"{node_id} agent {node.get('agent_id')} != {EXPECTED_AGENT_MAPPING[node_id]}"))
        for section in ("input_fields", "output_fields"):
            for field in node.get(section, []):
                key = field.get("canonical_key")
                if key and key not in field_keys:
                    findings.append(finding("node_io", "error", "contracts/v26/node_io_contract.yaml", f"{node_id} {section} unknown field {key}"))
                if field.get("source_type") in BAD_STATUS_VALUES:
                    findings.append(finding("node_io", "error", "contracts/v26/node_io_contract.yaml", f"{node_id} old source_type {field.get('source_type')}"))


def audit_architecture(findings: list[dict[str, str]]) -> None:
    nodes = load_json(ROOT / "architecture" / "node_registry.json")["nodes"]
    edges = load_json(ROOT / "architecture" / "edge_registry.json")["edges"]
    scenarios = load_json(ROOT / "architecture" / "scenario_chain_registry.json")["scenarios"]
    mappings = load_json(ROOT / "architecture" / "node_agent_mapping.json")["mappings"]
    node_ids = {node["id"] for node in nodes}
    edge_ids = {edge["edge_id"] for edge in edges}
    if len(nodes) != 22:
        findings.append(finding("node_registry", "error", "architecture/node_registry.json", f"node count {len(nodes)} != 22"))
    if len(edges) != 67:
        findings.append(finding("edge_registry", "error", "architecture/edge_registry.json", f"edge count {len(edges)} != 67"))
    if len(scenarios) != 10:
        findings.append(finding("scenario_chain", "error", "architecture/scenario_chain_registry.json", f"scenario count {len(scenarios)} != 10"))
    for edge in edges:
        if edge.get("source_node_id") not in node_ids or edge.get("target_node_id") not in node_ids:
            findings.append(finding("edge_registry", "error", "architecture/edge_registry.json", f"{edge.get('edge_id')} references missing node"))
        if not edge.get("why"):
            findings.append(finding("edge_registry", "error", "architecture/edge_registry.json", f"{edge.get('edge_id')} missing why"))
    for scenario in scenarios:
        if not set(scenario.get("nodes") or []).issubset(node_ids):
            findings.append(finding("scenario_chain", "error", "architecture/scenario_chain_registry.json", f"{scenario.get('id')} references missing node"))
        if not set(scenario.get("required_edges") or []).issubset(edge_ids):
            findings.append(finding("scenario_chain", "error", "architecture/scenario_chain_registry.json", f"{scenario.get('id')} references missing edge"))
    for item in mappings:
        expected = EXPECTED_AGENT_MAPPING.get(item.get("node_id"))
        if expected and item.get("agent_id") != expected:
            findings.append(finding("agent_mapping", "error", "architecture/node_agent_mapping.json", f"{item.get('node_id')} agent mismatch"))


def audit_text_drift(findings: list[dict[str, str]], strict_docs: bool) -> None:
    for path in iter_scan_files():
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        if rel in {"runtime/v26_contract_validator.py", "tests/contracts/test_v26_field_registry.py"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in BAD_DOC_VERSION_PATTERNS:
            if pattern in text:
                severity = "error" if strict_docs else "info"
                findings.append(finding("legacy_reference", severity, rel, f"legacy reference found: {pattern}"))
        if rel.startswith("contracts/") and rel.endswith((".yaml", ".json")):
            for bad in BAD_STATUS_VALUES:
                if f'"{bad}"' in text:
                    findings.append(finding("contract_status", "error", rel, f"old status value found: {bad}"))
        if "字段覆盖率率" in text or "待命名字段" in text:
            findings.append(finding("naming", "error", rel, "unresolved naming marker"))


def write_reports(findings: list[dict[str, str]]) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "ok" if not any(item["severity"] == "error" for item in findings) else "failed",
        "finding_count": len(findings),
        "error_count": sum(1 for item in findings if item["severity"] == "error"),
        "findings": findings,
    }
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# V26 Contract Drift Audit", "", f"- status: {payload['status']}", f"- findings: {payload['finding_count']}", f"- errors: {payload['error_count']}", ""]
    for item in findings:
        lines.append(f"- [{item['severity']}] {item['kind']} `{item['path']}`: {item['message']}")
    MD_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-docs", action="store_true")
    args = parser.parse_args(argv)
    findings: list[dict[str, str]] = []
    field_keys = audit_field_registry(findings)
    audit_node_io(field_keys, findings)
    audit_architecture(findings)
    audit_text_drift(findings, args.strict_docs)
    write_reports(findings)
    error_count = sum(1 for item in findings if item["severity"] == "error")
    print(json.dumps({"status": "ok" if error_count == 0 else "failed", "errors": error_count, "json": str(JSON_OUT), "md": str(MD_OUT)}, ensure_ascii=False))
    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
