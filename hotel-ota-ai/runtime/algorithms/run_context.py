from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any

from runtime.common import DEFAULT_DB, PACKAGE_ROOT
from runtime.demo_facts import load_demo_fact, load_demo_manifest
from runtime.storage import connect


FACT_NAMES = [
    "business_snapshot",
    "room_types",
    "orders_aggregate",
    "price_history",
    "sales_baseline",
    "progress_deviation",
    "market_context",
    "competitors",
    "reputation",
    "promotion",
    "customer_segments",
    "execution_preview",
    "external_ota_report_fields",
]

SAFETY_FIELDS = {
    "today_label_allowed": False,
    "approval_data_allowed": False,
    "live_allowed": False,
    "formal_approval_allowed": False,
    "formal_approval_created": False,
    "live_execution_count": 0,
}


def _loads_json(value: str | bytes | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _static_demo_facts() -> dict[str, dict[str, Any]]:
    return {name: load_demo_fact(f"{name}.json") for name in FACT_NAMES}


def _static_manifest() -> dict[str, Any]:
    manifest = load_demo_manifest()
    return {
        "demo_dataset_id": manifest.get("demo_dataset_id"),
        "hotel_id": manifest.get("hotel_id"),
        "hotel_name": manifest.get("hotel_name"),
        "business_date": manifest.get("demo_business_date"),
        "demo_business_date": manifest.get("demo_business_date"),
        "data_business_date": manifest.get("demo_business_date"),
        "data_source_type": "demo_data",
        "freshness_status": "demo_data",
        "business_status": "demo_or_historical",
        "synthetic_data": False,
        "real_pms_data": False,
        "real_ota_data": False,
        **SAFETY_FIELDS,
    }


def latest_generated_today_facts(db_path: str = DEFAULT_DB, hotel_id: str | None = None) -> dict[str, Any] | None:
    try:
        with closing(connect(db_path)) as conn:
            params: list[Any] = []
            where = "source LIKE 'synthetic_today_demo:%'"
            if hotel_id:
                where += " AND hotel_id=?"
                params.append(hotel_id)
            latest = conn.execute(
                f"""
                SELECT hotel_id, captured_at
                FROM snapshots
                WHERE {where}
                ORDER BY captured_at DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
            if latest is None:
                return None
            rows = conn.execute(
                """
                SELECT source, payload_json
                FROM snapshots
                WHERE hotel_id=? AND captured_at=? AND source LIKE 'synthetic_today_demo:%'
                """,
                (latest["hotel_id"], latest["captured_at"]),
            ).fetchall()
            hotel = conn.execute("SELECT config_json, name FROM hotels WHERE hotel_id=?", (latest["hotel_id"],)).fetchone()
    except Exception:
        return None
    facts: dict[str, dict[str, Any]] = {}
    for row in rows:
        fact_name = str(row["source"]).split(":", 1)[-1]
        facts[fact_name] = _loads_json(row["payload_json"])
    if not facts:
        return None
    manifest = dict(facts.get("generated_demo_manifest") or {})
    hotel_config = _loads_json(hotel["config_json"] if hotel else None)
    manifest.setdefault("demo_dataset_id", hotel_config.get("demo_dataset_id"))
    manifest.setdefault("hotel_id", latest["hotel_id"])
    manifest.setdefault("hotel_name", hotel["name"] if hotel else latest["hotel_id"])
    manifest.setdefault("data_source_type", "synthetic_today_demo")
    manifest.setdefault("freshness_status", "synthetic_current_day")
    manifest.setdefault("business_status", "demo_or_historical")
    manifest.setdefault("synthetic_data", True)
    manifest.setdefault("real_pms_data", False)
    manifest.setdefault("real_ota_data", False)
    manifest.update(SAFETY_FIELDS)
    return {"manifest": manifest, "facts": facts, "captured_at": latest["captured_at"], "db_path": db_path}


def build_run_context(
    *,
    db_path: str = DEFAULT_DB,
    hotel_id: str | None = None,
    use_generated_today: bool = False,
    demo_data_dir: str | Path | None = None,
    strict_generated_today: bool = False,
) -> dict[str, Any]:
    generated = latest_generated_today_facts(db_path, hotel_id=hotel_id)
    if generated:
        facts = generated["facts"]
        manifest = dict(generated["manifest"])
        source = "sqlite_synthetic_today_demo"
        context_warnings: list[str] = []
    elif use_generated_today and strict_generated_today:
        return {
            "status": "data_gap",
            "run_context_version": "v27-p0p1",
            "context_source": "missing_sqlite_synthetic_today_demo",
            "use_generated_today": False,
            "requested_generated_today": True,
            "strict_generated_today": True,
            "demo_data_dir": str(demo_data_dir or PACKAGE_ROOT / "examples" / "demo_data"),
            "demo_data_dir_label": str(demo_data_dir or PACKAGE_ROOT / "examples" / "demo_data"),
            "db_path": db_path,
            "fallback_used": False,
            "generated_demo_run_id": None,
            "generated_at": None,
            "manifest": {
                "hotel_id": hotel_id,
                "data_source_type": "unavailable",
                "freshness_status": "missing_date",
                "business_status": "data_gap",
                **SAFETY_FIELDS,
            },
            "facts": {},
            "business_date": None,
            "hotel_id": hotel_id,
            "core_metrics": {},
            "context_warnings": ["generated_today_demo_not_found", "strict_generated_today_no_static_fallback"],
            **SAFETY_FIELDS,
            "data_source_type": "unavailable",
            "freshness_status": "missing_date",
            "business_status": "data_gap",
        }
    else:
        facts = _static_demo_facts()
        manifest = _static_manifest()
        source = "static_demo_fixtures"
        context_warnings = ["generated_today_demo_not_found"] if use_generated_today else []
    for fact in facts.values():
        if isinstance(fact, dict):
            fact.update({key: value for key, value in manifest.items() if key in {"demo_dataset_id", "hotel_id", "data_source_type", "freshness_status", "business_status"}})
            fact.update(SAFETY_FIELDS)
    business = facts.get("business_snapshot") or {}
    return {
        "status": "ok",
        "run_context_version": "v27-p0p1",
        "context_source": source,
        "use_generated_today": bool(generated),
        "requested_generated_today": bool(use_generated_today),
        "strict_generated_today": bool(strict_generated_today),
        "demo_data_dir": str(demo_data_dir or PACKAGE_ROOT / "examples" / "demo_data"),
        "demo_data_dir_label": str(demo_data_dir or PACKAGE_ROOT / "examples" / "demo_data"),
        "db_path": db_path if generated else None,
        "fallback_used": not bool(generated),
        "generated_demo_run_id": manifest.get("generated_demo_run_id") or manifest.get("run_id") or manifest.get("demo_dataset_id"),
        "generated_at": generated.get("captured_at") if generated else manifest.get("generated_at"),
        "manifest": manifest,
        "facts": facts,
        "business_date": business.get("business_date") or business.get("demo_business_date") or manifest.get("business_date"),
        "hotel_id": manifest.get("hotel_id") or business.get("hotel_id") or hotel_id,
        "core_metrics": {
            "total_rooms": business.get("total_rooms"),
            "sold_rooms": business.get("sold_rooms"),
            "available_rooms": business.get("available_rooms"),
            "occupancy_rate": business.get("occupancy_rate"),
            "adr": business.get("adr"),
            "revpar": business.get("revpar"),
        },
        "context_warnings": context_warnings,
        **SAFETY_FIELDS,
        "data_source_type": manifest.get("data_source_type"),
        "freshness_status": manifest.get("freshness_status"),
        "business_status": "demo_or_historical",
    }
