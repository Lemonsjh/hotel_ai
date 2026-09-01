from __future__ import annotations

from functools import lru_cache
from typing import Any

from runtime.v27_contract_loader import load_v27_contract


@lru_cache(maxsize=1)
def skills_by_id() -> dict[str, dict[str, Any]]:
    return {str(skill["skill_id"]): dict(skill) for skill in load_v27_contract()["skills"].values()}


def get_skill(skill_id: str) -> dict[str, Any]:
    normalized = str(skill_id).upper()
    skill = skills_by_id().get(normalized)
    if not skill:
        raise KeyError(f"unknown V27 skill: {skill_id}")
    return dict(skill)


def skill_ids() -> set[str]:
    return set(skills_by_id())
