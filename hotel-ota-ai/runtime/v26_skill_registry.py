from __future__ import annotations

from functools import lru_cache
from typing import Any

from runtime.v26_contract_loader import load_v26_skill_io_contract


@lru_cache(maxsize=1)
def skills_by_id() -> dict[str, dict[str, Any]]:
    contract = load_v26_skill_io_contract()
    return {str(skill["skill_id"]): dict(skill) for skill in contract.get("skills", [])}


def get_skill(skill_id: str) -> dict[str, Any]:
    skill = skills_by_id().get(str(skill_id))
    if not skill:
        raise KeyError(f"unknown V26 skill: {skill_id}")
    return dict(skill)
