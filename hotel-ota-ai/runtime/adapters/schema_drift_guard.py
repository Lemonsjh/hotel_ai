from __future__ import annotations

import copy
import inspect
import json
import os
import tempfile
from functools import wraps
from pathlib import Path
from typing import Any, Callable


_STATS_PERIOD_COLUMN = "stats_period_type"
_RECOVERY_RISK = "schema_drift_recovered:stats_period_type_mapping_removed"


def _is_stats_period_type_schema_drift(exc: BaseException) -> bool:
    message = " ".join(str(item) for item in getattr(exc, "args", ()) if item is not None) or str(exc)
    lowered = message.lower()
    return "unknown column" in lowered and _STATS_PERIOD_COLUMN in lowered


def _remove_stats_period_type_mappings(config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    sanitized = copy.deepcopy(config)
    removed: list[str] = []
    profiles = sanitized.get("profiles") or {}
    if not isinstance(profiles, dict):
        return sanitized, removed

    for profile_name, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        table_columns = profile.get("columns") or {}
        if not isinstance(table_columns, dict):
            continue
        for table_key, mappings in table_columns.items():
            if not isinstance(mappings, dict):
                continue
            for canonical_key, physical_column in list(mappings.items()):
                if str(canonical_key) == _STATS_PERIOD_COLUMN or str(physical_column) == _STATS_PERIOD_COLUMN:
                    mappings.pop(canonical_key, None)
                    removed.append(f"{profile_name}.{table_key}.{canonical_key}")
    return sanitized, removed


def _temporary_sanitized_mapping(path: str) -> tuple[str | None, list[str]]:
    source = Path(path)
    if not source.is_file():
        return None, []
    try:
        with source.open("r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None, []
    if not isinstance(config, dict):
        return None, []

    sanitized, removed = _remove_stats_period_type_mappings(config)
    if not removed:
        return None, []

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix="hotel-ota-db-mapping-sanitized-",
        delete=False,
    )
    try:
        json.dump(sanitized, handle, ensure_ascii=False, indent=2)
        handle.flush()
        return handle.name, removed
    finally:
        handle.close()


def _schema_drift_result(*, template: str | None, exc: BaseException, removed: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": "data_gap",
        "reason": "database_schema_drift_stats_period_type",
        "template": template,
        "error_type": exc.__class__.__name__,
        "risk_flags": ["database_schema_drift", "stats_period_type_mapping_invalid"],
        "removed_mapping_paths": removed or [],
        "message": (
            "The mapping profile references stats_period_type, but the source table does not contain that column. "
            "Remove or correct the optional mapping; no database column is fabricated."
        ),
    }


def _mark_recovered(result: dict[str, Any], removed: list[str]) -> dict[str, Any]:
    result = dict(result)
    top_risks = list(result.get("risk_flags") or [])
    if _RECOVERY_RISK not in top_risks:
        top_risks.append(_RECOVERY_RISK)
    result["risk_flags"] = top_risks
    result["schema_drift_recovered"] = True
    result["removed_mapping_paths"] = removed

    payload = result.get("payload")
    if isinstance(payload, dict):
        payload = dict(payload)
        payload_risks = list(payload.get("risk_flags") or [])
        if _RECOVERY_RISK not in payload_risks:
            payload_risks.append(_RECOVERY_RISK)
        payload["risk_flags"] = payload_risks
        payload["schema_drift_recovered"] = True
        payload["removed_mapping_paths"] = removed
        result["payload"] = payload
    return result


def guard_database_template_result(original: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    if getattr(original, "_stats_period_schema_guard", False):
        return original

    signature = inspect.signature(original)

    @wraps(original)
    def guarded(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return original(*args, **kwargs)
        except Exception as exc:
            if not _is_stats_period_type_schema_drift(exc):
                raise

            bound = signature.bind_partial(*args, **kwargs)
            template = bound.arguments.get("template")
            mapping_path = bound.arguments.get("mapping_config") or os.environ.get("HOTEL_OTA_DB_MAPPING_CONFIG")
            if not mapping_path:
                return _schema_drift_result(template=template, exc=exc)

            sanitized_path, removed = _temporary_sanitized_mapping(str(mapping_path))
            if not sanitized_path:
                return _schema_drift_result(template=template, exc=exc, removed=removed)

            try:
                bound.arguments["mapping_config"] = sanitized_path
                retry_result = original(*bound.args, **bound.kwargs)
                return _mark_recovered(retry_result, removed)
            except Exception as retry_exc:
                return _schema_drift_result(template=template, exc=retry_exc, removed=removed)
            finally:
                try:
                    os.unlink(sanitized_path)
                except OSError:
                    pass

    guarded._stats_period_schema_guard = True  # type: ignore[attr-defined]
    return guarded


def install_database_schema_drift_guard() -> None:
    from runtime.adapters import database

    database.database_template_result = guard_database_template_result(database.database_template_result)
