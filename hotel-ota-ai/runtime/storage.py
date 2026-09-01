from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from runtime.common import DEFAULT_DB, DEFAULT_LOG_DIR, emit, json_dumps, now_local
from runtime.demo_facts import business_snapshot, load_demo_manifest, room_types


def ensure_dirs(db_path: str = DEFAULT_DB) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(DEFAULT_LOG_DIR).mkdir(parents=True, exist_ok=True)


def connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    ensure_dirs(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("PRAGMA journal_mode=WAL")
        cursor.close()
    except Exception:
        conn.close()
        raise
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS hotels (
          hotel_id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          org_id TEXT,
          pms_vendor TEXT,
          timezone TEXT DEFAULT 'Asia/Shanghai',
          config_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS room_types (
          hotel_id TEXT NOT NULL,
          room_type_id TEXT NOT NULL,
          name TEXT NOT NULL,
          floor_price REAL,
          ceiling_price REAL,
          inventory INTEGER,
          config_json TEXT NOT NULL DEFAULT '{}',
          PRIMARY KEY (hotel_id, room_type_id)
        );
        CREATE TABLE IF NOT EXISTS snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          hotel_id TEXT NOT NULL,
          captured_at TEXT NOT NULL,
          source TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS baselines (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          hotel_id TEXT NOT NULL,
          business_date TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(hotel_id, business_date)
        );
        CREATE TABLE IF NOT EXISTS approvals (
          approval_id TEXT PRIMARY KEY,
          hotel_id TEXT NOT NULL,
          action_type TEXT NOT NULL,
          status TEXT NOT NULL,
          requested_by TEXT,
          approved_by TEXT,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS api_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          hotel_id TEXT,
          method TEXT NOT NULL,
          request_summary_json TEXT NOT NULL,
          response_summary_json TEXT,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS calendar_days (
          date TEXT PRIMARY KEY,
          year INTEGER NOT NULL,
          month INTEGER NOT NULL,
          day INTEGER NOT NULL,
          weekday INTEGER NOT NULL,
          is_weekend INTEGER NOT NULL,
          is_workday INTEGER NOT NULL,
          is_holiday INTEGER NOT NULL,
          is_adjusted_workday INTEGER NOT NULL,
          is_off_day INTEGER NOT NULL,
          holiday_name TEXT,
          holiday_group TEXT,
          days_to_holiday INTEGER,
          days_after_holiday INTEGER,
          season_tag TEXT NOT NULL,
          school_vacation_tag TEXT NOT NULL,
          local_event_count INTEGER NOT NULL DEFAULT 0,
          event_heat_level TEXT NOT NULL DEFAULT 'none',
          demand_level TEXT NOT NULL,
          price_advice TEXT NOT NULL,
          source_quality TEXT NOT NULL,
          source TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS event_candidates (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          hotel_id TEXT NOT NULL,
          date TEXT NOT NULL,
          event_name TEXT NOT NULL,
          event_type TEXT,
          location TEXT,
          distance_km REAL,
          source_url TEXT,
          confidence REAL NOT NULL DEFAULT 0,
          expected_heat TEXT NOT NULL DEFAULT 'unknown',
          status TEXT NOT NULL DEFAULT 'candidate',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS experience_candidates (
          candidate_id TEXT PRIMARY KEY,
          hotel_id TEXT NOT NULL,
          source_scenario TEXT,
          source_node TEXT,
          source_skill TEXT,
          experience_type TEXT,
          observation TEXT NOT NULL,
          proposed_rule TEXT,
          evidence_json TEXT,
          risk_level TEXT DEFAULT 'low',
          status TEXT DEFAULT 'candidate',
          requires_human INTEGER DEFAULT 1,
          privacy_ok INTEGER DEFAULT 0,
          created_at TEXT,
          reviewed_at TEXT,
          reviewed_by TEXT,
          promoted_to TEXT,
          approval_data INTEGER DEFAULT 0,
          live_data INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_experience_candidates_hotel_status
          ON experience_candidates(hotel_id, status, created_at);
        CREATE TABLE IF NOT EXISTS command_menus (
          menu_id TEXT PRIMARY KEY,
          chat_id TEXT NOT NULL,
          starter_open_id TEXT NOT NULL,
          starter_role TEXT NOT NULL,
          hotel_id TEXT NOT NULL,
          status TEXT NOT NULL,
          selected_command_id TEXT,
          expires_at TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_command_menus_chat_status
          ON command_menus(chat_id, status, expires_at);
        CREATE INDEX IF NOT EXISTS idx_command_menus_owner_status
          ON command_menus(chat_id, starter_open_id, status, expires_at);
        CREATE TABLE IF NOT EXISTS config_change_requests (
          request_id TEXT PRIMARY KEY,
          request_kind TEXT NOT NULL,
          hotel_id TEXT NOT NULL,
          requester_principal_id TEXT NOT NULL,
          requester_role TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          payload_hash TEXT NOT NULL,
          nonce_hash TEXT NOT NULL,
          request_chat_hash TEXT,
          expires_at TEXT NOT NULL,
          status TEXT NOT NULL,
          approver_principal_id TEXT,
          approver_role TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_config_change_requests_hotel_status
          ON config_change_requests(hotel_id, status, created_at);
        CREATE TABLE IF NOT EXISTS configuration_audit_events (
          event_id TEXT PRIMARY KEY,
          hotel_id TEXT NOT NULL,
          request_id TEXT NOT NULL,
          actor_principal_id TEXT NOT NULL,
          actor_role TEXT NOT NULL,
          action TEXT NOT NULL,
          payload_hash TEXT NOT NULL,
          previous_event_hash TEXT,
          event_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_configuration_audit_hotel
          ON configuration_audit_events(hotel_id, created_at, event_id);
        CREATE TABLE IF NOT EXISTS price_guard_policies (
          policy_id TEXT PRIMARY KEY,
          hotel_id TEXT NOT NULL,
          room_type_id TEXT NOT NULL,
          channel_source TEXT,
          ota_product_id TEXT,
          floor_price REAL NOT NULL,
          ceiling_price REAL NOT NULL,
          max_single_change_pct REAL NOT NULL,
          max_increase_pct REAL,
          max_decrease_pct REAL,
          min_increase_pct REAL,
          min_decrease_pct REAL,
          effective_from TEXT NOT NULL,
          effective_to TEXT,
          version INTEGER NOT NULL,
          status TEXT NOT NULL,
          source_request_id TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_price_guard_policy_active
          ON price_guard_policies(hotel_id, room_type_id, status, effective_from, effective_to, version);
        CREATE TABLE IF NOT EXISTS role_map_apply_queue (
          queue_id TEXT PRIMARY KEY,
          request_id TEXT NOT NULL UNIQUE,
          hotel_id TEXT NOT NULL,
          patch_json TEXT NOT NULL,
          expected_config_hash TEXT,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          applied_at TEXT
        );
        CREATE TABLE IF NOT EXISTS auth_principals (
          principal_id TEXT PRIMARY KEY,
          open_id TEXT UNIQUE,
          user_id TEXT UNIQUE,
          union_id TEXT UNIQUE,
          display_name TEXT,
          alias TEXT,
          name_snapshot TEXT,
          is_global_admin INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_backend_state (
          backend_name TEXT PRIMARY KEY,
          status TEXT NOT NULL,
          schema_version INTEGER NOT NULL,
          activated_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hotel_memberships (
          principal_id TEXT NOT NULL,
          hotel_id TEXT NOT NULL,
          role TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (principal_id, hotel_id)
        );
        CREATE TABLE IF NOT EXISTS group_chat_bindings (
          chat_id TEXT PRIMARY KEY,
          hotel_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_bindings (
          chat_id TEXT PRIMARY KEY,
          chat_type TEXT NOT NULL DEFAULT 'unknown',
          hotel_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          source TEXT NOT NULL DEFAULT 'sqlite_active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chat_bindings_hotel_status
          ON chat_bindings(hotel_id, status, chat_type);
        CREATE TABLE IF NOT EXISTS chat_binding_requests (
          request_id TEXT PRIMARY KEY,
          hotel_id TEXT NOT NULL,
          chat_id_hash TEXT NOT NULL,
          chat_type TEXT NOT NULL,
          operation TEXT NOT NULL,
          payload_hash TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          status TEXT NOT NULL,
          requester_principal_id TEXT NOT NULL,
          requester_role TEXT NOT NULL,
          approver_principal_id TEXT,
          approver_role TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS role_change_requests (
          request_id TEXT PRIMARY KEY,
          hotel_id TEXT NOT NULL,
          target_principal_id TEXT NOT NULL,
          requested_role TEXT NOT NULL,
          operation TEXT NOT NULL,
          payload_hash TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feishu_chat_registry (
          chat_id_hash TEXT PRIMARY KEY,
          chat_type TEXT NOT NULL,
          bound_hotel_id TEXT,
          binding_status TEXT NOT NULL DEFAULT 'unbound',
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          source_account_id_hash TEXT,
          member_count_snapshot INTEGER
        );
        CREATE TABLE IF NOT EXISTS feishu_message_audit (
          audit_id TEXT PRIMARY KEY,
          event_id TEXT,
          correlation_id TEXT,
          chat_id_hash TEXT,
          sender_identity_hash TEXT,
          message_text_redacted TEXT,
          intent TEXT,
          auth_backend TEXT,
          auth_status TEXT,
          tenant_status TEXT,
          role TEXT,
          blocked_reason TEXT,
          renderer_template TEXT,
          send_allowed INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feishu_message_audit_created
          ON feishu_message_audit(created_at, intent, auth_status);
        CREATE TABLE IF NOT EXISTS meituan_ota_goods_price_mapping (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          hotel_name TEXT,
          snapshot_time TEXT,
          channel_source TEXT,
          pms_room_type_id TEXT,
          pms_room_type_name TEXT,
          ota_room_type_id TEXT,
          room_type_name TEXT NOT NULL,
          business_date TEXT NOT NULL,
          ota_product_id TEXT NOT NULL,
          ota_product_name TEXT,
          rate_plan_name TEXT,
          is_super_deal INTEGER,
          ota_sale_price REAL,
          commission_rate REAL
        );
        CREATE INDEX IF NOT EXISTS idx_meituan_price_mapping_room_date
          ON meituan_ota_goods_price_mapping(business_date, room_type_name, ota_product_id);
        CREATE TABLE IF NOT EXISTS ctrip_ota_goods_price_mapping (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          hotel_name TEXT,
          snapshot_time TEXT,
          channel_source TEXT,
          hotel_id TEXT,
          ota_room_type_id TEXT,
          room_type_name TEXT NOT NULL,
          business_date TEXT NOT NULL,
          ota_product_id TEXT NOT NULL,
          ota_product_name TEXT,
          product_cipher TEXT,
          price_editable_flag INTEGER,
          is_hour_room INTEGER,
          ota_sale_price REAL,
          commission_rate REAL
        );
        CREATE INDEX IF NOT EXISTS idx_ctrip_price_mapping_room_date
          ON ctrip_ota_goods_price_mapping(business_date, room_type_name, ota_product_id);
        CREATE TABLE IF NOT EXISTS meituan_zhiting_price_task (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          hotel_name TEXT NOT NULL,
          ota_product_id TEXT NOT NULL,
          room_type_name TEXT NOT NULL,
          business_date TEXT NOT NULL,
          target_sale_price REAL NOT NULL,
          execute_status TEXT NOT NULL CHECK (execute_status IN ('PENDING', 'SUCCESS', 'FAILED')),
          created_at TEXT NOT NULL,
          source_decision_id TEXT,
          created_by TEXT,
          error_message TEXT,
          executed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_meituan_zhiting_pending
          ON meituan_zhiting_price_task(ota_product_id, business_date, execute_status);
        CREATE TABLE IF NOT EXISTS ctrip_zhiting_price_task (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          hotel_name TEXT NOT NULL,
          ota_product_id TEXT NOT NULL,
          room_type_name TEXT NOT NULL,
          business_date TEXT NOT NULL,
          target_sale_price REAL NOT NULL,
          execute_status TEXT NOT NULL CHECK (execute_status IN ('PENDING', 'SUCCESS', 'FAILED')),
          created_at TEXT NOT NULL,
          product_cipher TEXT,
          source_decision_id TEXT,
          created_by TEXT,
          error_message TEXT,
          executed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ctrip_zhiting_pending
          ON ctrip_zhiting_price_task(ota_product_id, business_date, execute_status);
        """
    )
    _ensure_column(conn, "price_guard_policies", "max_increase_pct", "REAL")
    _ensure_column(conn, "price_guard_policies", "max_decrease_pct", "REAL")
    _ensure_column(conn, "price_guard_policies", "min_increase_pct", "REAL")
    _ensure_column(conn, "price_guard_policies", "min_decrease_pct", "REAL")
    _ensure_column(conn, "price_guard_policies", "channel_source", "TEXT")
    _ensure_column(conn, "price_guard_policies", "ota_product_id", "TEXT")
    _ensure_column(conn, "config_change_requests", "request_chat_hash", "TEXT")
    _ensure_column(conn, "auth_principals", "is_global_admin", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "auth_principals", "display_name", "TEXT")
    _ensure_column(conn, "auth_principals", "alias", "TEXT")
    _ensure_column(conn, "auth_principals", "name_snapshot", "TEXT")
    _ensure_column(conn, "role_change_requests", "requester_principal_id", "TEXT")
    _ensure_column(conn, "role_change_requests", "requester_role", "TEXT")
    _ensure_column(conn, "role_change_requests", "request_chat_hash", "TEXT")
    _ensure_column(conn, "role_change_requests", "approver_principal_id", "TEXT")
    _ensure_column(conn, "role_change_requests", "approver_role", "TEXT")
    _ensure_column(conn, "role_change_requests", "approved_at", "TEXT")
    for task_table in ("ctrip_zhiting_price_task", "meituan_zhiting_price_task"):
        _ensure_column(conn, task_table, "room_type_id", "TEXT")
        _ensure_column(conn, task_table, "source_decision_id", "TEXT")
        _ensure_column(conn, task_table, "created_by", "TEXT")
        _ensure_column(conn, task_table, "error_message", "TEXT")
        _ensure_column(conn, task_table, "executed_at", "TEXT")
    _ensure_column(conn, "ctrip_zhiting_price_task", "room_type_name", "TEXT")
    _ensure_column(conn, "meituan_ota_goods_price_mapping", "hotel_name", "TEXT")
    _ensure_column(conn, "ctrip_ota_goods_price_mapping", "hotel_name", "TEXT")
    for mapping_table in ("meituan_ota_goods_price_mapping", "ctrip_ota_goods_price_mapping"):
        _ensure_column(conn, mapping_table, "hotel_id", "TEXT")
        _ensure_column(conn, mapping_table, "room_type_id", "TEXT")
        _ensure_column(conn, mapping_table, "source_product_id", "TEXT")
        _ensure_column(conn, mapping_table, "source_room_type_id", "TEXT")
        _ensure_column(conn, mapping_table, "source_room_type_name", "TEXT")
        _ensure_column(conn, mapping_table, "source_platform", "TEXT")
        _ensure_column(conn, mapping_table, "mapping_status", "TEXT")
        _ensure_column(conn, mapping_table, "is_active", "INTEGER")
        _ensure_column(conn, mapping_table, "price_editable_flag", "INTEGER")
        _ensure_column(conn, mapping_table, "is_hour_room", "INTEGER")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """Apply additive SQLite migrations without rewriting existing policy rows."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    try:
        columns = {str(row["name"]) for row in cursor}
    finally:
        cursor.close()
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db(args: argparse.Namespace) -> None:
    with closing(connect(args.db)) as conn:
        with conn:
            init_schema(conn)
    emit({"status": "ok", "db": args.db, "message": "hotel OTA runtime database initialized"})


def _seed_hotel(conn: sqlite3.Connection, hotel_id: str, hotel_name: str, ts: str) -> None:
    config_json = json_dumps(
        {
            "roles": {"owner": ["approve_execute"], "operator": ["diagnose"], "frontdesk": ["report"]},
            "channels": ["Mtop", "QZAgent", "meituan"],
            "pricing": {"single_change_limit_pct": 0.15, "default_requires_approval": True},
            "demo_dataset_id": load_demo_manifest()["demo_dataset_id"],
        }
    )
    conn.execute(
        """
        INSERT INTO hotels (hotel_id, name, org_id, pms_vendor, timezone, config_json, created_at, updated_at)
        VALUES (?, ?, '', 'Beyondh', 'Asia/Shanghai', ?, ?, ?)
        ON CONFLICT(hotel_id) DO UPDATE SET
          name=excluded.name,
          pms_vendor=excluded.pms_vendor,
          timezone=excluded.timezone,
          config_json=excluded.config_json,
          updated_at=excluded.updated_at
        """,
        (hotel_id, hotel_name, config_json, ts, ts),
    )


def _seed_room_types(conn: sqlite3.Connection, hotel_id: str) -> int:
    count = 0
    for room in room_types():
        conn.execute(
            """
            INSERT INTO room_types (hotel_id, room_type_id, name, floor_price, ceiling_price, inventory, config_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hotel_id, room_type_id) DO UPDATE SET
              name=excluded.name,
              floor_price=excluded.floor_price,
              ceiling_price=excluded.ceiling_price,
              inventory=excluded.inventory,
              config_json=excluded.config_json
            """,
            (
                hotel_id,
                room["room_type_id"],
                room["room_type_name"],
                room["floor_price"],
                room["ceiling_price"],
                room["inventory"],
                json_dumps(room),
            ),
        )
        count += 1
    return count


def _seed_snapshot_and_baseline(conn: sqlite3.Connection, hotel_id: str, ts: str, snapshot: dict[str, Any]) -> dict[str, int]:
    payload = dict(snapshot)
    payload["hotel_id"] = hotel_id
    conn.execute(
        """
        INSERT INTO snapshots (hotel_id, captured_at, source, payload_json)
        VALUES (?, ?, 'demo_data', ?)
        """,
        (hotel_id, ts, json_dumps(payload)),
    )
    conn.execute(
        """
        INSERT INTO baselines (hotel_id, business_date, payload_json, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(hotel_id, business_date) DO UPDATE SET
          payload_json=excluded.payload_json,
          created_at=excluded.created_at
        """,
        (hotel_id, payload["demo_business_date"], json_dumps(payload), ts),
    )
    return {"snapshots": 1, "baselines": 1}


def seed_demo_result(db_path: str = DEFAULT_DB) -> dict[str, Any]:
    ts = now_local()
    run_id = f"seed-demo-{uuid.uuid4().hex[:12]}"
    manifest = load_demo_manifest()
    snapshot = business_snapshot()
    primary_hotel_id = manifest["hotel_id"]
    compatibility_hotel_ids = [
        str(hotel_id)
        for hotel_id in manifest.get("legacy_compatibility_hotel_ids", [])
        if hotel_id and str(hotel_id) != str(primary_hotel_id)
    ]
    inserted_rows = {"hotels": 0, "room_types": 0, "snapshots": 0, "baselines": 0}
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            for hotel_id in [primary_hotel_id, *compatibility_hotel_ids]:
                _seed_hotel(conn, hotel_id, manifest["hotel_name"], ts)
                inserted_rows["hotels"] += 1
                inserted_rows["room_types"] += _seed_room_types(conn, hotel_id)
                seeded = _seed_snapshot_and_baseline(conn, hotel_id, ts, snapshot)
                inserted_rows["snapshots"] += seeded["snapshots"]
                inserted_rows["baselines"] += seeded["baselines"]
    return {
        "status": "ok",
        "run_id": run_id,
        "generated_by_runtime": True,
        "db_path": db_path,
        "demo_dataset_id": manifest["demo_dataset_id"],
        "hotel_id": primary_hotel_id,
        "compatibility_hotel_ids": compatibility_hotel_ids,
        "legacy_compatibility_hotel_ids": compatibility_hotel_ids,
        "legacy_compatibility_note": "Compatibility hotel ids support old local demos only and are excluded from core acceptance.",
        "inserted_tables": [key for key, value in inserted_rows.items() if value],
        "inserted_rows": inserted_rows,
        "latest_business_date": manifest["demo_business_date"],
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def seed_demo(args: argparse.Namespace) -> None:
    emit(seed_demo_result(args.db))


def log_api(
    hotel_id: str | None,
    method: str,
    request_summary: dict[str, Any],
    response_summary: dict[str, Any],
    status: str,
    db: str,
) -> None:
    with closing(connect(db)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO api_logs (hotel_id, method, request_summary_json, response_summary_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    hotel_id,
                    method,
                    json_dumps(request_summary),
                    json_dumps(response_summary),
                    status,
                    now_local(),
                ),
            )


def approval_create(args: argparse.Namespace) -> None:
    payload = json.loads(args.payload)
    from runtime.safety.approvals import validate_approval_payload

    payload_gate = validate_approval_payload(payload, args.action_type)
    if not payload_gate["allowed"]:
        emit(
            {
                "status": "blocked",
                "reason": payload_gate["reason"],
                "approval_required": False,
                "template_id": payload_gate.get("template_id"),
                "payload_gate": payload_gate,
            }
        )
        return
    approval_id = f"appr-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    ts = now_local()
    with closing(connect(args.db)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO approvals (approval_id, hotel_id, action_type, status, requested_by, approved_by, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, NULL, ?, ?, ?)
                """,
                (approval_id, args.hotel_id, args.action_type, args.requested_by, json_dumps(payload), ts, ts),
            )
    emit(
        {
            "status": "ok",
            "approval_id": approval_id,
            "approval_status": "pending",
            "data_business_date": payload.get("data_business_date"),
            "data_snapshot_time": payload.get("data_snapshot_time"),
            "freshness_status": payload.get("freshness_status"),
            "dry_run_summary": payload.get("dry_run_summary"),
        }
    )


def approval_get(db_path: str, approval_id: str | None) -> dict[str, Any] | None:
    if not approval_id:
        return None
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT approval_id, hotel_id, action_type, status, requested_by, approved_by, payload_json, created_at, updated_at
            FROM approvals WHERE approval_id=?
            """,
            (approval_id,),
        ).fetchone()
    if row is None:
        return None
    record = dict(row)
    try:
        record["payload"] = json.loads(record.pop("payload_json"))
    except json.JSONDecodeError:
        record["payload"] = {}
    return record


def approval_mark(args: argparse.Namespace) -> None:
    status = "approved" if args.approve else "rejected"
    with closing(connect(args.db)) as conn:
        with conn:
            cur = conn.execute(
                "UPDATE approvals SET status=?, approved_by=?, updated_at=? WHERE approval_id=?",
                (status, args.user, now_local(), args.approval_id),
            )
    emit({"status": "ok" if cur.rowcount else "not_found", "approval_id": args.approval_id, "approval_status": status})
