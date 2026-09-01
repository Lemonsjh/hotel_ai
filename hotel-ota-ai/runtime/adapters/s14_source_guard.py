from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, Callable


_BLOCKED_TEMPLATE = "operation_diagnosis"


def guard_s14_direct_database_source(
    original: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    if getattr(original, "_s14_direct_source_guard", False):
        return original

    signature = inspect.signature(original)

    @wraps(original)
    def guarded(*args: Any, **kwargs: Any) -> dict[str, Any]:
        bound = signature.bind_partial(*args, **kwargs)
        template = bound.arguments.get("template")
        if template == _BLOCKED_TEMPLATE:
            return {
                "status": "data_gap",
                "template": template,
                "skill_id": "S14",
                "blocked_reason": "s14_direct_source_removed_use_versioned_capability_results",
                "missing_inputs": ["capability_results"],
                "source_policy": "versioned_capability_results_only",
                "direct_business_table_read_allowed": False,
                "write_performed": False,
                "direct_execution_allowed": False,
                "live_allowed": False,
            }
        return original(*args, **kwargs)

    guarded._s14_direct_source_guard = True  # type: ignore[attr-defined]
    return guarded


def install_s14_direct_database_source_guard() -> None:
    from runtime.adapters import database

    database.database_template_result = guard_s14_direct_database_source(
        database.database_template_result
    )
