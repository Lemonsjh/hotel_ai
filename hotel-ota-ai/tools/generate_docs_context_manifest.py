from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests" / "docs_context_manifest.yaml"

STARTUP_DOCS = [
    "AGENTS.md",
    "BOOTSTRAP.md",
    "TOOLS.md",
    "README.md",
    "USER.md",
    "IDENTITY.md",
    "SOUL.md",
    "HEARTBEAT.md",
    "MEMORY.md",
]

AUTHORITATIVE_PATHS = [
    "contracts/v27/",
    "docs/architecture_reference/v27/",
    "architecture/",
    "router/",
    "skills/hotel-ota/",
]

OPERATIONAL_PATHS = [
    "ops/",
    "manifests/deploy_manifest.yaml",
    "manifests/runtime_manifest.yaml",
]

EXCLUDED_PATHS = [
    "requirements/",
    "docs/architecture_reference/v26/",
]


def iter_markdown_files() -> list[Path]:
    """Return active Markdown files, excluding metadata and retired requirements."""
    ignored = {".git", "__pycache__", ".claude", ".codex", ".trae", "requirements"}
    files: list[Path] = []
    for path in ROOT.rglob("*.md"):
        if any(part in ignored for part in path.parts):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def _quoted_list(lines: list[str], key: str, values: list[str], indent: int = 2) -> None:
    prefix = " " * indent
    lines.append(f"{prefix}{key}:")
    for value in values:
        lines.append(f'{prefix}  - "{value}"')


def generate_manifest() -> str:
    lines = [
        "schema_version: docs_context_manifest.v2",
        "current_fact_source: contracts/v27/contract.json",
        "current_runtime_mode: single_openclaw_controller_with_A0_A6_logical_agents",
        "context_groups:",
        "  openclaw_startup:",
        '    policy: "read_first"',
    ]
    _quoted_list(lines, "documents", STARTUP_DOCS, indent=4)
    lines.extend([
        "  authoritative_v27:",
        '    policy: "read_when_relevant"',
    ])
    _quoted_list(lines, "paths", AUTHORITATIVE_PATHS, indent=4)
    lines.extend([
        "  operations:",
        '    policy: "read_when_deploying_or_operating"',
    ])
    _quoted_list(lines, "paths", OPERATIONAL_PATHS, indent=4)
    _quoted_list(lines, "excluded_paths", EXCLUDED_PATHS, indent=0)
    lines.extend([
        "rules:",
        '  - "Runtime and contracts/v27 override documentation when they conflict."',
        '  - "Legacy requirements are retired and must not be restored as active context."',
        '  - "Private configuration, credentials, identities, DSNs, and tokens stay outside Git."',
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(generate_manifest(), encoding="utf-8")
    print(MANIFEST.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
