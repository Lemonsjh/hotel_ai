from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


BLOCKING_STATUSES = {"data_gap", "stale", "schema_drift", "blocked", "error"}

DEFAULT_DEPENDENCIES: dict[str, list[str]] = {
    "S16_PROGRESS_DEVIATION": ["S15_SALES_BASELINE"],
    "S5_REVENUE_DECISION": [
        "S2_OPERATING_SNAPSHOT",
        "S4_MARKET_CONTEXT",
        "S15_SALES_BASELINE",
        "S16_PROGRESS_DEVIATION",
        "OTA_PRICE_MAPPING",
    ],
    "S14_OPERATION_DIAGNOSIS": [
        "S2_OPERATING_SNAPSHOT",
        "S4_MARKET_CONTEXT",
        "S7_COMPETITIVE_MONITORING",
        "S8_PROMOTION_PLANNING",
        "S9_TRAFFIC_PEAK_VALLEY",
        "S10_ROI_DECISION",
        "S12_REPUTATION_MANAGEMENT",
        "S15_SALES_BASELINE",
        "S16_PROGRESS_DEVIATION",
        "S17_CUSTOMER_ORDER_ANALYSIS",
    ],
    "S14_EXT_THIRD_PARTY": [
        "WEATHER_CONTEXT",
        "LOCAL_EVENTS",
        "HOLIDAY_CONTEXT",
        "BUSINESS_CALENDAR",
    ],
}

NON_BLOCKING_DEPENDENCY_TARGETS = {"S14_OPERATION_DIAGNOSIS"}


@dataclass(slots=True)
class SkillRun:
    skill: str
    status: str
    result: dict[str, Any] = field(default_factory=dict)

    def compact(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"skill": self.skill, "status": self.status}
        reason = self.result.get("reason") or self.result.get("blocked_reason")
        if reason:
            payload["reason"] = reason
        return payload


def _status_of(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return "error"
    return str(result.get("status") or result.get("source_status") or "ok")


def run_skill_with_dependencies(
    *,
    target_skill: str,
    hotel_id: str,
    context: dict[str, Any] | None = None,
    runner: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
    dependencies: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Run a target skill after collecting its registered upstream capabilities."""

    context = dict(context or {})
    dependency_map = dependencies or DEFAULT_DEPENDENCIES
    required = list(dependency_map.get(target_skill, []))
    dependency_runs: list[SkillRun] = []

    if runner is None:
        return {
            "target_skill": target_skill,
            "hotel_id": hotel_id,
            "dependency_runs": [],
            "final_result": None,
            "blocked": True,
            "blocked_reason": "skill_runner_missing",
        }

    collect_all = target_skill in NON_BLOCKING_DEPENDENCY_TARGETS
    for dependency in required:
        result = runner(dependency, hotel_id, context)
        run = SkillRun(skill=dependency, status=_status_of(result), result=result)
        dependency_runs.append(run)
        context.setdefault("dependency_results", {})[dependency] = result
        if run.status in BLOCKING_STATUSES and not collect_all:
            return {
                "target_skill": target_skill,
                "hotel_id": hotel_id,
                "dependency_runs": [item.compact() for item in dependency_runs],
                "final_result": None,
                "blocked": True,
                "blocked_reason": "dependency_data_gap" if run.status == "data_gap" else "dependency_blocked",
                "blocking_dependency": dependency,
            }

    final_result = runner(target_skill, hotel_id, context)
    final_status = _status_of(final_result)
    return {
        "target_skill": target_skill,
        "hotel_id": hotel_id,
        "dependency_runs": [item.compact() for item in dependency_runs],
        "final_result": final_result,
        "blocked": final_status in BLOCKING_STATUSES,
        "blocked_reason": None if final_status not in BLOCKING_STATUSES else "target_skill_blocked",
        "dependency_collection_policy": "collect_all_and_degrade_modules" if collect_all else "fail_fast",
    }


def dependency_config_path(root: str | Path | None = None) -> Path:
    base = Path(root) if root else Path.cwd()
    return base / "config" / "skill-dependencies.yaml"
