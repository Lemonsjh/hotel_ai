#!/usr/bin/env python3
"""Validate one hotel’s multi-tenant configuration without exposing secrets."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = Path(os.environ.get("HOTEL_OTA_ENV_FILE", "/etc/hotel-ota-ai/hotel-ota.env"))


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_json(path: str) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def check(name: str, ok: bool, required: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "status": "ok" if ok else ("blocked" if required else "missing"), "required": required, "detail": detail}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one hotel onboarding configuration.")
    parser.add_argument("--hotel-id", required=True)
    parser.add_argument("--chief-account", required=True)
    parser.add_argument("--s14-account", required=True)
    args = parser.parse_args()
    load_env()
    mapping_path = os.environ.get("HOTEL_OTA_DB_MAPPING_CONFIG", "/etc/hotel-ota-ai/database-source.json")
    db = load_json(mapping_path)
    role = load_json(os.environ.get("HOTEL_OTA_AUTH_CONFIG", "/etc/hotel-ota-ai/feishu-role-map.json"))
    s14 = load_json(os.environ.get("S14_ACCOUNT_MAP", "/etc/hotel-ota-ai/s14-account-map.json"))
    market = load_json("/etc/hotel-ota-ai/market-source.json")
    s14_sources = load_json("/etc/hotel-ota-ai/s14-source.json")
    hotel = args.hotel_id
    profile_name = (db.get("hotel_profile_map") or {}).get(hotel)
    profile = (db.get("profiles") or {}).get(profile_name or "") or {}
    suffix = hotel.upper().replace("-", "_")
    checks = [
        check("chief_account_scope", (role.get("bot_account_hotel_map") or {}).get(args.chief_account) == hotel, True, "chief account must map to this hotel"),
        check("s14_account_scope", ((s14.get("bots") or {}).get(args.s14_account) or {}).get("hotel_id") == hotel, True, "S14 account must map to this hotel"),
        check("database_profile", bool(profile_name) and hotel in (profile.get("hotel_ids") or {}), True, "hotel profile must declare only this hotel identity"),
        check("main_read_dsn", bool(os.environ.get(f"HOTEL_OTA_DB_DSN_{suffix}")), True, "exact hotel read DSN is required"),
        check("s14_source", bool((s14_sources.get("hotels") or {}).get(hotel)), False, "S14 source is optional but required for S14 reports"),
        check("market_source", bool((market.get("hotels") or {}).get(hotel)), False, "required for market/competitor capabilities"),
    ]
    for label, base in (("price_task", "HOTEL_OTA_PRICE_TASK_DB_DSN"), ("review_task", "HOTEL_OTA_REVIEW_TASK_DSN"), ("promotion_control", "HOTEL_OTA_PROMOTION_CONTROL_DSN")):
        checks.append(check(label, bool(os.environ.get(f"{base}_{suffix}")), False, "exact hotel writer DSN; missing capability stays fail-closed"))
    critical = [item for item in checks if item["required"] and item["status"] != "ok"]
    print(json.dumps({"hotel_id": hotel, "status": "blocked" if critical else "ready_with_gaps", "checks": checks}, ensure_ascii=False, indent=2))
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
