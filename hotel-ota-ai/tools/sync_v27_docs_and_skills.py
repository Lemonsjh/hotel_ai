from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

NOTICE_MD = """## V27 Contract-First Notice

当前以 `contracts/v27/contract.json` 为唯一 machine-readable 工程契约。V26 文件仅作为 legacy migration reference 和历史协作资料；如旧说明与 V27 contract/runtime 冲突，以 V27 为准。
"""

NOTICE_QUOTE = """> V27 Contract-First Notice
>
> 当前以 `contracts/v27/contract.json` 为唯一 machine-readable 工程契约。V26 文件仅作为 legacy migration reference 和历史协作资料；如旧说明与 V27 contract/runtime 冲突，以 V27 为准。

"""


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def replace_v26_notice(text: str, quote: bool = False) -> str:
    replacement = NOTICE_QUOTE if quote else NOTICE_MD + "\n"
    if "V27 Contract-First Notice" in text:
        return text
    if "V26 Registry-First Notice" in text:
        lines = text.splitlines()
        end = 0
        for index, line in enumerate(lines):
            if index == 0 or line.startswith(">") or line.strip() == "":
                end = index + 1
                continue
            break
        if quote:
            return replacement + "\n".join(lines[end:]).lstrip("\n")
        if lines and lines[0].startswith("## V26 Registry-First Notice"):
            end = 0
            for index, line in enumerate(lines):
                if index < 5 or line.strip() == "":
                    end = index + 1
                    continue
                break
            return replacement + "\n".join(lines[end:]).lstrip("\n")
    return replacement + text


def sync_root_docs() -> None:
    replacements = {
        "V26 字段契约与全链路演示": "V27 字段契约与全链路演示",
        "现在以 V26 为准重新对齐": "现在以 contracts/v27/contract.json 为唯一工程契约重新对齐",
        "docs/architecture_reference/v26/": "docs/architecture_reference/v26/（legacy migration reference）",
        "contracts/v26/": "contracts/v27/",
        "V26 架构事实源": "V27 工程契约事实源",
        "字段契约见 `contracts/v26/`": "字段契约见 `contracts/v27/contract.json` 和 `contracts/v27/` 派生文件",
        "V26 JSON/xlsx/drawio 已归档在": "V26 JSON/xlsx/drawio 仅作为 legacy migration reference 归档在",
        "以 `contracts/v26/` 为准": "以 `contracts/v27/contract.json` 为准",
        "当旧说明与 V26 注册层冲突时，以 `docs/architecture_reference/v26/（legacy migration reference）`、`architecture/`、`contracts/v27/` 和 runtime 安全模块为准。": "当旧说明与 V27 contract/runtime 冲突时，以 `contracts/v27/contract.json` 和 runtime 安全模块为准。",
        "V27 工程契约事实源见 `docs/architecture_reference/v26/（legacy migration reference）` 与 `architecture/`": "V27 工程契约事实源见 `contracts/v27/contract.json`",
        "`references/v26_alignment.json`": "`references/v27_alignment.json`",
    }
    for name in ["README.md", "AGENTS.md", "BOOTSTRAP.md", "TOOLS.md", "MEMORY.md", "USER.md", "IDENTITY.md", "SOUL.md", "HEARTBEAT.md"]:
        path = ROOT / name
        if not path.exists():
            continue
        text = read(path)
        if name in {"README.md", "AGENTS.md", "BOOTSTRAP.md", "TOOLS.md", "MEMORY.md"}:
            text = replace_v26_notice(text, quote=False)
        for old, new in replacements.items():
            text = text.replace(old, new)
        if name in {"USER.md", "IDENTITY.md", "SOUL.md", "HEARTBEAT.md", "MEMORY.md"}:
            for line in ["不是权限来源。", "不是业务数据来源。", "不是审批依据。"]:
                if line not in text:
                    text += f"\n- {line}\n"
        write(path, text)


def sync_requirement_docs() -> None:
    for path in sorted((ROOT / "requirements").glob("*")):
        if path.suffix.lower() not in {".md", ".yaml", ".yml"}:
            continue
        text = read(path)
        text = replace_v26_notice(text, quote=path.suffix.lower() == ".md")
        text = text.replace("contracts/v26/", "contracts/v27/")
        text = text.replace("references/v26_alignment.json", "references/v27_alignment.json")
        text = text.replace("V26 Registry-First Notice", "V27 Contract-First Notice")
        text = text.replace("V26 registry", "V27 contract")
        text = text.replace("V26 registries", "V27 contract")
        write(path, text)


def sync_architecture_docs() -> None:
    for path in sorted((ROOT / "architecture").glob("*.md")):
        text = read(path)
        text = replace_v26_notice(text, quote=False)
        text = text.replace("contracts/v26/", "contracts/v27/")
        text = text.replace("references/v26_alignment.json", "references/v27_alignment.json")
        text = text.replace("V26 registries", "V27 contract")
        text = text.replace("V26 registry", "V27 contract")
        write(path, text)


def sync_skills() -> None:
    skill_contract = json.loads((ROOT / "contracts" / "v27" / "skill_io_contract.yaml").read_text(encoding="utf-8"))
    skills_by_id = {skill["skill_id"]: skill for skill in skill_contract["skills"]}
    for skill_dir in sorted((ROOT / "skills" / "hotel-ota").glob("s*")):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        text = read(skill_md)
        text = text.replace("## V26 架构绑定", "## V27 架构绑定")
        text = text.replace("V26 alignment", "V27 alignment")
        text = text.replace("V26 对齐", "V27 对齐")
        text = text.replace("references/v26_alignment.json", "references/v27_alignment.json")
        write(skill_md, text)

        rules = skill_dir / "references" / "rules.md"
        if rules.exists():
            rules_text = read(rules)
            rules_text = rules_text.replace("V26 可施工算法规格", "V27 可施工算法规格")
            rules_text = rules_text.replace("contracts/v26/", "contracts/v27/")
            write(rules, rules_text)

        legacy = skill_dir / "references" / "v26_alignment.json"
        skill_id = None
        if legacy.exists():
            try:
                skill_id = json.loads(legacy.read_text(encoding="utf-8")).get("skill_id")
            except json.JSONDecodeError:
                skill_id = None
        if not skill_id:
            for candidate in skills_by_id:
                if skill_dir.name.startswith(candidate.lower().replace("_", "-")):
                    skill_id = candidate
                    break
        if not skill_id:
            skill_id = next((item for item in skills_by_id if item.lower().replace("-", "") in skill_dir.name.lower().replace("-", "")), None)
        if skill_id and skill_id in skills_by_id:
            payload = dict(skills_by_id[skill_id])
            payload.update(
                {
                    "schema_version": "v27.0",
                    "source": "contracts/v27/contract.json",
                    "field_registry_ref": "contracts/v27/field_registry.yaml",
                    "node_io_contract_ref": "contracts/v27/node_io_contract.yaml",
                    "legacy_v26_alignment_ref": "references/v26_alignment.json",
                    "demo_safety_fields": [
                        "data_source_type=demo_data",
                        "freshness_status=demo_data",
                        "approval_data_allowed=false",
                        "live_allowed=false",
                    ],
                }
            )
            (skill_dir / "references" / "v27_alignment.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    shared = ROOT / "skills" / "hotel-ota" / "_shared" / "v27-alignment-policy.md"
    shared.write_text(
        "# V27 Alignment Policy\n\n"
        "`contracts/v27/contract.json` is the current machine-readable contract. "
        "`contracts/v26` and `references/v26_alignment.json` are legacy migration references only.\n",
        encoding="utf-8",
    )


def sync_algorithm_rules() -> None:
    for path in sorted((ROOT / "runtime" / "algorithm_rules").glob("*.yaml")):
        text = read(path)
        text = text.replace("references/v26_alignment.json", "references/v27_alignment.json")
        text = text.replace("contracts/v26/", "contracts/v27/")
        write(path, text)


def main() -> int:
    sync_root_docs()
    sync_requirement_docs()
    sync_architecture_docs()
    sync_skills()
    sync_algorithm_rules()
    print(json.dumps({"status": "ok", "source": "contracts/v27/contract.json"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
