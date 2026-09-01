from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_S14_SOURCE_CONFIG = "/etc/hotel-ota-ai/s14-source.json"


def _load_config(config_path: str | None = None) -> dict[str, Any]:
    path = config_path or os.environ.get("HOTEL_OTA_S14_SOURCE_CONFIG")
    if not path and Path(DEFAULT_S14_SOURCE_CONFIG).exists():
        path = DEFAULT_S14_SOURCE_CONFIG
    if not path:
        return {"status": "data_gap", "reason": "s14_source_config_not_configured"}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"status": "data_gap", "reason": "s14_source_config_not_found"}
    except json.JSONDecodeError as exc:
        return {"status": "data_gap", "reason": f"s14_source_config_invalid_json:{exc.msg}"}


def resolve_s14_source(config_path: str | None, *, hotel_id: str, source_key: str) -> dict[str, Any]:
    config = _load_config(config_path)
    if config.get("status") == "data_gap":
        return config
    hotel = ((config.get("hotels") or {}).get(hotel_id) or {})
    sources = hotel.get("s14_sources") or {}
    source = sources.get(source_key)
    if not isinstance(source, dict):
        return {"status": "data_gap", "reason": "s14_source_key_not_registered", "source_key": source_key}
    if not source.get("enabled", True):
        return {"status": "data_gap", "reason": "s14_source_disabled", "source_key": source_key}
    mode = source.get("source_mode")
    if mode not in {"excel", "mysql"}:
        return {"status": "data_gap", "reason": "s14_source_mode_not_supported", "source_key": source_key}
    result = {
        "status": "ok",
        "source_key": source_key,
        "source_mode": mode,
        "hotel_id": hotel_id,
    }
    if mode == "excel":
        path = source.get("path")
        if not path:
            return {"status": "data_gap", "reason": "s14_registered_excel_path_missing", "source_key": source_key}
        result["path"] = str(path)
        result["path_exists"] = Path(path).exists()
    else:
        profile = source.get("profile")
        if not profile:
            return {"status": "data_gap", "reason": "s14_registered_mysql_profile_missing", "source_key": source_key}
        result["profile"] = str(profile)
    return result
