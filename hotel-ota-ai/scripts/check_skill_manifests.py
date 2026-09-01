from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
REQUIRED_FILES = ("openclaw.skill.yaml", "SKILL.md", "config/triggers.yaml")
COMMON_REQUIRED = (
    "runtime",
    "data_gap",
    "approval",
    "verified role",
    "demo/sample/synthetic",
    "no private path",
)
WRITE_REQUIRED = ("write_performed", "audit_id", "affected_rows")
PRICE_REQUIRED = ("price_guard",)
FORBIDDEN_SKILL_DIRS = (SKILLS_ROOT / "ota-diagnosis",)
SUPPLEMENT_MARKER = "<!-- OpenClaw skill standardization supplement -->"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _skill_dirs() -> list[Path]:
    if not SKILLS_ROOT.exists():
        return []
    return sorted(path.parent for path in SKILLS_ROOT.rglob("SKILL.md"))


def _is_price_skill(path: Path) -> bool:
    name = path.name.lower()
    manifest = _text(path / "openclaw.skill.yaml").lower() if (path / "openclaw.skill.yaml").exists() else ""
    triggers = _text(path / "config/triggers.yaml").lower() if (path / "config/triggers.yaml").exists() else ""
    command_text = manifest + "\n" + triggers
    return any(term in name for term in ("price", "revenue-decision")) or any(
        term in command_text for term in ("execute-price", "revenue-decision")
    )


def _is_execution_skill(path: Path) -> bool:
    name = path.name.lower()
    manifest = _text(path / "openclaw.skill.yaml").lower() if (path / "openclaw.skill.yaml").exists() else ""
    triggers = _text(path / "config/triggers.yaml").lower() if (path / "config/triggers.yaml").exists() else ""
    command_text = manifest + "\n" + triggers
    return any(term in name for term in ("execution", "price")) or any(
        term in command_text for term in ("execute-price", "promotion-execute")
    )


def _contains_all(content: str, keywords: tuple[str, ...]) -> list[str]:
    lowered = content.lower()
    return [keyword for keyword in keywords if keyword.lower() not in lowered]


def _validate_yaml_shape(path: Path) -> list[str]:
    problems: list[str] = []
    text = _text(path)
    for key in ("name:", "description:", "instructions:", "notes:"):
        if not re.search(rf"(?m)^{re.escape(key)}", text):
            problems.append(f"{path.relative_to(ROOT)} missing {key}")
    return problems


def _validate_generated_text(skill_dir: Path) -> list[str]:
    problems: list[str] = []
    generated_texts = {
        "openclaw.skill.yaml": _text(skill_dir / "openclaw.skill.yaml"),
        "config/triggers.yaml": _text(skill_dir / "config/triggers.yaml"),
    }
    skill_text = _text(skill_dir / "SKILL.md")
    if SUPPLEMENT_MARKER in skill_text:
        generated_texts["SKILL.md supplement"] = skill_text.split(SUPPLEMENT_MARKER, 1)[1]
    for label, content in generated_texts.items():
        if "\ufffd" in content or "???" in content:
            problems.append(f"{skill_dir.relative_to(ROOT)} generated {label} contains mojibake marker")
    return problems


def check() -> list[str]:
    problems: list[str] = []
    for forbidden in FORBIDDEN_SKILL_DIRS:
        if forbidden.exists():
            problems.append(f"forbidden skill directory exists: {forbidden.relative_to(ROOT)}")

    skills = _skill_dirs()
    if not skills:
        problems.append("no existing skill directories with SKILL.md found")
        return problems

    for skill_dir in skills:
        missing_files = []
        for rel in REQUIRED_FILES:
            if not (skill_dir / rel).exists():
                missing_files.append(rel)
                problems.append(f"{skill_dir.relative_to(ROOT)} missing {rel}")
        if missing_files:
            continue

        combined = "\n".join(_text(skill_dir / rel) for rel in REQUIRED_FILES)
        missing = _contains_all(combined, COMMON_REQUIRED)
        if "guardrail" not in combined.lower() and "护栏" not in combined:
            missing.append("guardrail/护栏")
        for keyword in missing:
            problems.append(f"{skill_dir.relative_to(ROOT)} missing keyword: {keyword}")

        if _is_price_skill(skill_dir):
            for keyword in _contains_all(combined, PRICE_REQUIRED):
                problems.append(f"{skill_dir.relative_to(ROOT)} price skill missing keyword: {keyword}")
        if _is_execution_skill(skill_dir):
            for keyword in _contains_all(combined, WRITE_REQUIRED):
                problems.append(f"{skill_dir.relative_to(ROOT)} execution skill missing keyword: {keyword}")

        problems.extend(_validate_yaml_shape(skill_dir / "openclaw.skill.yaml"))
        problems.extend(_validate_generated_text(skill_dir))

        trigger_text = _text(skill_dir / "config/triggers.yaml")
        for key in ("intent:", "phrases:", "required_role:", "command_name:", "runtime_command:", "data_guardrails:", "output_guardrails:", "examples:"):
            if not re.search(rf"(?m)^{re.escape(key)}", trigger_text):
                problems.append(f"{(skill_dir / 'config/triggers.yaml').relative_to(ROOT)} missing {key}")

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("Skill manifest check failed:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print(f"Skill manifest check passed: {len(_skill_dirs())} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
