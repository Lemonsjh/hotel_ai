from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.cli import main as cli_main
from runtime.safety.payload_hash import price_execution_payload, price_execution_payload_hash
from runtime.storage import connect, init_schema
from runtime.adapters.zhiting_price_task_outbox import (
    ALLOWED_EXECUTE_STATUSES,
    _product_skip_reason,
    _task_table,
    read_price_task_status,
    write_zhiting_price_tasks,
)


class TestZhitingPriceTaskOutbox(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self._tmp.name) / "outbox.sqlite")
        with contextlib.closing(connect(self.db_path)) as conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO meituan_ota_goods_price_mapping
                  (hotel_name, channel_source, room_type_name, business_date, ota_product_id, ota_product_name, ota_sale_price, commission_rate)
                VALUES
                  ('璞悦酒店', 'meituan', 'KING', '2026-06-30', 'mt-prod-1', 'KING-无早', 188, 0.12),
                  ('璞悦酒店', 'meituan', 'KING', '2026-06-30', 'mt-prod-2', 'KING-双早', 198, 0.12)
                """
            )
            conn.execute(
                """
                INSERT INTO ctrip_ota_goods_price_mapping
                  (hotel_name, channel_source, room_type_name, business_date, ota_product_id, ota_product_name, product_cipher, price_editable_flag, ota_sale_price, commission_rate)
                VALUES
                  ('璞悦酒店', 'ctrip', 'KING', '2026-06-30', 'ct-prod-1', 'KING-可取消', 'cipher-a', 1, 188, 0.10),
                  ('璞悦酒店', 'ctrip', 'KING', '2026-06-30', 'ct-prod-2', 'KING-不可编辑', 'cipher-b', 0, 188, 0.10),
                  ('璞悦酒店', 'ctrip', 'KING', '2026-06-30', 'ct-prod-3', 'KING-缺签名', NULL, 1, 188, 0.10)
                """
            )
            conn.commit()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_schema_adds_required_task_fields_without_old_statuses(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            for table in ("ctrip_zhiting_price_task", "meituan_zhiting_price_task"):
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                for expected in {
                    "hotel_name",
                    "ota_product_id",
                    "room_type_name",
                    "business_date",
                    "target_sale_price",
                    "execute_status",
                    "created_at",
                    "source_decision_id",
                    "created_by",
                    "error_message",
                    "executed_at",
                }:
                    self.assertIn(expected, columns)
            self.assertEqual(ALLOWED_EXECUTE_STATUSES, {"PENDING", "SUCCESS", "FAILED"})
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO meituan_zhiting_price_task
                      (hotel_name, ota_product_id, room_type_name, business_date, target_sale_price, execute_status, created_at)
                    VALUES ('璞悦酒店', 'x', 'KING', '2026-06-30', 199, 'RUNNING', '2026-06-26 10:00:00')
                    """
                )

    def test_mysql_dialect_defaults_to_current_price_task_tables(self) -> None:
        self.assertEqual(_task_table("meituan", dialect="mysql"), "meituan_price_task")
        self.assertEqual(_task_table("ctrip", dialect="mysql"), "ctrip_price_task")
        self.assertEqual(_task_table("meituan", dialect="sqlite"), "meituan_zhiting_price_task")

    def test_sqlite_outbox_can_write_to_configured_current_table_name(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute("UPDATE meituan_ota_goods_price_mapping SET hotel_name=NULL")
            conn.execute(
                """
                CREATE TABLE meituan_price_task (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  hotel_name TEXT,
                  channel_source TEXT,
                  room_type_name TEXT,
                  ota_product_id TEXT,
                  ota_product_name TEXT,
                  business_date TEXT,
                  current_sale_price REAL,
                  target_sale_price REAL,
                  price_delta REAL,
                  price_delta_pct REAL,
                  execute_status TEXT,
                  review_status TEXT,
                  plugin_status TEXT,
                  verification_status TEXT,
                  created_at TEXT
                )
                """
            )
            conn.commit()
        old_value = os.environ.get("HOTEL_OTA_PRICE_TASK_TABLE_MEITUAN")
        os.environ["HOTEL_OTA_PRICE_TASK_TABLE_MEITUAN"] = "meituan_price_task"
        try:
            result = write_zhiting_price_tasks(
                self.db_path,
                channel_source="meituan",
                hotel_name="鐠炴偊閰掑簵",
                room_type_name="KING",
                ota_product_id="mt-prod-1",
                business_date="2026-06-30",
                target_sale_price=199,
                source_decision_id="DEC-CURRENT-TABLE",
                created_by="owner-1",
                write_enabled=True,
                confirmed=True,
                allowed_channels=["meituan"],
                now="2026-06-26 10:00:00",
            )
        finally:
            if old_value is None:
                os.environ.pop("HOTEL_OTA_PRICE_TASK_TABLE_MEITUAN", None)
            else:
                os.environ["HOTEL_OTA_PRICE_TASK_TABLE_MEITUAN"] = old_value

        self.assertEqual(result["status"], "queued")
        with contextlib.closing(connect(self.db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM meituan_price_task").fetchone()["count"]
            row = conn.execute("SELECT execute_status, review_status, plugin_status FROM meituan_price_task LIMIT 1").fetchone()
        self.assertEqual(count, 1)
        self.assertEqual(dict(row), {"execute_status": "PENDING", "review_status": "approved", "plugin_status": "pending"})

    def test_meituan_multi_product_room_type_requires_ota_product_id(self) -> None:
        # KING 房型下有 mt-prod-1/mt-prod-2 两个商品(价差):不带 --ota-product-id
        # 不得把同一目标价灌给所有商品,应 block 要求指定商品(防团购价被挂牌价覆盖)。
        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="meituan",
            hotel_name="璞悦酒店",
            room_type_name="KING",
            business_date="2026-06-30",
            target_sale_price=199,
            source_decision_id="DEC-AMBIG",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["meituan"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "price_task_requires_ota_product_id")
        self.assertEqual(result["inserted_task_count"], 0)
        self.assertFalse(result["write_performed"])
        with contextlib.closing(connect(self.db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM meituan_zhiting_price_task").fetchone()["c"]
        self.assertEqual(count, 0)

    def test_ota_product_id_targets_single_product_only(self) -> None:
        # 带 --ota-product-id 只写指定那一个商品,不动同房型其他商品。
        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="meituan",
            hotel_name="璞悦酒店",
            room_type_name="KING",
            business_date="2026-06-30",
            target_sale_price=199,
            ota_product_id="mt-prod-1",
            source_decision_id="DEC-ONE",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["meituan"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["inserted_task_count"], 1)
        self.assertEqual(result["expanded_product_count"], 1)
        self.assertEqual(result["completion_scope"], "outbox_write_only")
        self.assertFalse(result["plugin_waited"])
        with contextlib.closing(connect(self.db_path)) as conn:
            rows = conn.execute("SELECT ota_product_id FROM meituan_zhiting_price_task").fetchall()
        self.assertEqual([row["ota_product_id"] for row in rows], ["mt-prod-1"])

    def test_meituan_targeted_product_write_keeps_business_date(self) -> None:
        # 按商品精确写:指定 mt-prod-1 只写该商品(不再灌给同房型全部商品),保留 business_date 等字段。
        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="meituan",
            hotel_name="璞悦酒店",
            room_type_name="KING",
            business_date="2026-06-30",
            target_sale_price=199,
            ota_product_id="mt-prod-1",
            source_decision_id="DEC-001",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["meituan"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["execute_status"], "PENDING")
        self.assertEqual(result["inserted_task_count"], 1)
        self.assertEqual(result["skipped_product_count"], 0)
        with contextlib.closing(connect(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT ota_product_id, business_date, created_at, execute_status, source_decision_id, created_by FROM meituan_zhiting_price_task ORDER BY ota_product_id"
            ).fetchall()
        self.assertEqual([row["ota_product_id"] for row in rows], ["mt-prod-1"])
        self.assertEqual({row["business_date"] for row in rows}, {"2026-06-30"})
        self.assertEqual({row["created_at"] for row in rows}, {"2026-06-26 10:00:00"})
        self.assertEqual({row["execute_status"] for row in rows}, {"PENDING"})
        self.assertEqual({row["source_decision_id"] for row in rows}, {"DEC-001"})
        self.assertEqual({row["created_by"] for row in rows}, {"owner-1"})

    def test_meituan_outbox_can_expand_by_canonical_room_type_id(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute("DELETE FROM meituan_ota_goods_price_mapping")
            conn.execute(
                """
                INSERT INTO meituan_ota_goods_price_mapping
                  (hotel_id, hotel_name, channel_source, room_type_id, room_type_name, business_date,
                   ota_product_id, ota_product_name, ota_sale_price, mapping_status, is_active,
                   price_editable_flag, is_hour_room)
                VALUES
                  ('hotel-a', 'Example Hotel', 'meituan', 'KING', '至臻电竞双床房', '2026-06-30',
                   'mt-prod-room-id', '双床无早', 188, 'CONFIRMED', 1, 1, 0)
                """
            )
            conn.commit()

        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="meituan",
            hotel_id="hotel-a",
            hotel_name="Example Hotel",
            room_type_id="KING",
            room_type_name="KING",
            business_date="2026-06-30",
            target_sale_price=199,
            source_decision_id="DEC-ROOM-ID",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["meituan"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["inserted_task_count"], 1)
        with contextlib.closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT ota_product_id, room_type_name, execute_status FROM meituan_zhiting_price_task WHERE source_decision_id='DEC-ROOM-ID'"
            ).fetchone()
        self.assertEqual(row["ota_product_id"], "mt-prod-room-id")
        self.assertEqual(row["room_type_name"], "至臻电竞双床房")
        self.assertEqual(row["execute_status"], "PENDING")

    def test_outbox_uses_hotel_room_type_mapping_to_expand_product_rows(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute("DELETE FROM meituan_ota_goods_price_mapping")
            conn.execute(
                """
                CREATE TABLE hotel_room_type_mapping (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  hotel_id TEXT,
                  hotel_name TEXT,
                  room_type_id TEXT,
                  room_type_name TEXT,
                  source_platform TEXT,
                  source_room_type_id TEXT,
                  source_room_type_name TEXT,
                  source_product_id TEXT,
                  source_product_name TEXT,
                  mapping_status TEXT,
                  is_active INTEGER,
                  price_editable_flag INTEGER,
                  is_hour_room INTEGER
                )
                """
            )
            conn.execute(
                """
                INSERT INTO hotel_room_type_mapping
                  (hotel_id, hotel_name, room_type_id, room_type_name, source_platform,
                   source_room_type_id, source_room_type_name, source_product_id, source_product_name,
                   mapping_status, is_active, price_editable_flag, is_hour_room)
                VALUES
                  ('hotel-a', 'Example Hotel', 'KING', 'King', 'meituan',
                   'mt-room-1', '至臻电竞双床房', 'mt-prod-map', '双床无早',
                   'CONFIRMED', 1, 1, 0)
                """
            )
            conn.execute(
                """
                INSERT INTO meituan_ota_goods_price_mapping
                  (hotel_id, hotel_name, channel_source, ota_room_type_id, room_type_name, business_date,
                   ota_product_id, ota_product_name, ota_sale_price)
                VALUES
                  ('hotel-a', 'Example Hotel', 'meituan', 'mt-room-1', '至臻电竞双床房', '2026-06-30',
                   'mt-prod-map', '双床无早', 188)
                """
            )
            conn.commit()

        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="meituan",
            hotel_id="hotel-a",
            hotel_name="Example Hotel",
            room_type_id="KING",
            room_type_name="KING",
            business_date="2026-06-30",
            target_sale_price=199,
            source_decision_id="DEC-MAPPING-TABLE",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["meituan"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["inserted_task_count"], 1)
        with contextlib.closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT ota_product_id, room_type_id, room_type_name FROM meituan_zhiting_price_task WHERE source_decision_id='DEC-MAPPING-TABLE'"
            ).fetchone()
        self.assertEqual(row["ota_product_id"], "mt-prod-map")
        self.assertEqual(row["room_type_id"], "KING")
        self.assertEqual(row["room_type_name"], "至臻电竞双床房")

    def test_match_rule_from_mapping_table_reaches_price_task_gate(self) -> None:
        # 真实库场景:outbox 源表 meituan_ota_goods_price_mapping 无 match_rule 列,
        # 可信身份信号 match_rule=ROOM_ID 只存在于 hotel_room_type_mapping。
        # mapping_status=AUTO(非 CONFIRMED)→ 唯一能过写闸的途径就是 match_rule 透传。
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute("DELETE FROM meituan_ota_goods_price_mapping")
            conn.execute(
                """
                CREATE TABLE hotel_room_type_mapping (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  hotel_id TEXT,
                  hotel_name TEXT,
                  room_type_id TEXT,
                  room_type_name TEXT,
                  source_platform TEXT,
                  source_room_type_id TEXT,
                  source_room_type_name TEXT,
                  source_product_id TEXT,
                  source_product_name TEXT,
                  mapping_status TEXT,
                  match_rule TEXT,
                  is_active INTEGER,
                  price_editable_flag INTEGER,
                  is_hour_room INTEGER
                )
                """
            )
            conn.execute(
                """
                INSERT INTO hotel_room_type_mapping
                  (hotel_id, hotel_name, room_type_id, room_type_name, source_platform,
                   source_room_type_id, source_room_type_name, source_product_id, source_product_name,
                   mapping_status, match_rule, is_active, price_editable_flag, is_hour_room)
                VALUES
                  ('hotel-a', 'Example Hotel', 'py03', '至臻·电竞双床房', 'meituan',
                   'mt-room-1', '至臻电竞双床房', 'mt-prod-map', '双床无早',
                   'AUTO', 'ROOM_ID', 1, 1, 0)
                """
            )
            conn.execute(
                """
                INSERT INTO meituan_ota_goods_price_mapping
                  (hotel_id, hotel_name, channel_source, ota_room_type_id, room_type_name, business_date,
                   ota_product_id, ota_product_name, ota_sale_price)
                VALUES
                  ('hotel-a', 'Example Hotel', 'meituan', 'mt-room-1', '至臻电竞双床房', '2026-06-30',
                   'mt-prod-map', '双床无早', 188)
                """
            )
            conn.commit()

        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="meituan",
            hotel_id="hotel-a",
            hotel_name="Example Hotel",
            room_type_id="py03",
            room_type_name="py03",
            business_date="2026-06-30",
            target_sale_price=199,
            source_decision_id="DEC-MATCH-RULE",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["meituan"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["inserted_task_count"], 1)
        with contextlib.closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT ota_product_id, room_type_id FROM meituan_zhiting_price_task WHERE source_decision_id='DEC-MATCH-RULE'"
            ).fetchone()
        self.assertEqual(row["ota_product_id"], "mt-prod-map")
        self.assertEqual(row["room_type_id"], "py03")

    def test_untrusted_match_rule_from_mapping_table_still_blocked(self) -> None:
        # 护栏:映射表 match_rule=NONE(非可信信号)且 mapping_status≠CONFIRMED
        # → 即使 match_rule 透传到闸,仍应 blocked(mapping_pending),证明修复未放宽护栏。
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute("DELETE FROM meituan_ota_goods_price_mapping")
            conn.execute(
                """
                CREATE TABLE hotel_room_type_mapping (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  hotel_id TEXT,
                  hotel_name TEXT,
                  room_type_id TEXT,
                  room_type_name TEXT,
                  source_platform TEXT,
                  source_room_type_id TEXT,
                  source_room_type_name TEXT,
                  source_product_id TEXT,
                  source_product_name TEXT,
                  mapping_status TEXT,
                  match_rule TEXT,
                  is_active INTEGER,
                  price_editable_flag INTEGER,
                  is_hour_room INTEGER
                )
                """
            )
            conn.execute(
                """
                INSERT INTO hotel_room_type_mapping
                  (hotel_id, hotel_name, room_type_id, room_type_name, source_platform,
                   source_room_type_id, source_room_type_name, source_product_id, source_product_name,
                   mapping_status, match_rule, is_active, price_editable_flag, is_hour_room)
                VALUES
                  ('hotel-a', 'Example Hotel', 'py03', '至臻·电竞双床房', 'meituan',
                   'mt-room-1', '至臻电竞双床房', 'mt-prod-map', '双床无早',
                   'AUTO', 'NONE', 1, 1, 0)
                """
            )
            conn.execute(
                """
                INSERT INTO meituan_ota_goods_price_mapping
                  (hotel_id, hotel_name, channel_source, ota_room_type_id, room_type_name, business_date,
                   ota_product_id, ota_product_name, ota_sale_price)
                VALUES
                  ('hotel-a', 'Example Hotel', 'meituan', 'mt-room-1', '至臻电竞双床房', '2026-06-30',
                   'mt-prod-map', '双床无早', 188)
                """
            )
            conn.commit()

        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="meituan",
            hotel_id="hotel-a",
            hotel_name="Example Hotel",
            room_type_id="py03",
            room_type_name="py03",
            business_date="2026-06-30",
            target_sale_price=199,
            source_decision_id="DEC-UNTRUSTED",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["meituan"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["inserted_task_count"], 0)
        self.assertEqual(result["skipped_product_count"], 1)
        self.assertEqual(result["skipped_products"][0]["reason"], "mapping_not_trusted")

    def test_ctrip_multi_product_requires_ota_product_id_after_editable_flag_removed(self) -> None:
        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="ctrip",
            hotel_name="璞悦酒店",
            room_type_name="KING",
            business_date="2026-06-30",
            target_sale_price=209,
            source_decision_id="DEC-CTRIP",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["ctrip"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "price_task_requires_ota_product_id")
        self.assertEqual(result["expanded_product_count"], 3)
        self.assertEqual(result["inserted_task_count"], 0)
        self.assertEqual(result["skipped_product_count"], 1)
        self.assertEqual(
            {item["reason"] for item in result["skipped_products"]},
            {"ctrip_product_cipher_missing"},
        )
        eligible = result["eligible_products"][0]
        self.assertEqual(eligible["product_type"], "listed_full_day")
        self.assertEqual(eligible["mapping_status"], "mapped")
        self.assertTrue(eligible["ready_for_price_task"])
        self.assertIn("price_guard_source", eligible)

    def test_ctrip_targeted_product_ignores_price_editable_flag_but_requires_cipher(self) -> None:
        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="ctrip",
            hotel_name="璞悦酒店",
            room_type_name="KING",
            ota_product_id="ct-prod-2",
            business_date="2026-06-30",
            target_sale_price=209,
            source_decision_id="DEC-CTRIP",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["ctrip"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["expanded_product_count"], 1)
        self.assertEqual(result["inserted_task_count"], 1)
        self.assertEqual(result["skipped_product_count"], 0)
        self.assertEqual(result["skipped_products"], [])
        with contextlib.closing(connect(self.db_path)) as conn:
            row = conn.execute("SELECT ota_product_id, room_type_name, product_cipher, execute_status FROM ctrip_zhiting_price_task").fetchone()
        self.assertEqual(row["ota_product_id"], "ct-prod-2")
        self.assertEqual(row["room_type_name"], "KING")
        self.assertEqual(row["product_cipher"], "cipher-b")
        self.assertEqual(row["execute_status"], "PENDING")

    def test_ctrip_accepts_decimal_editable_flag_from_mysql_profile(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO ctrip_ota_goods_price_mapping
                  (hotel_name, channel_source, room_type_name, business_date, ota_product_id, ota_product_name, product_cipher, price_editable_flag, ota_sale_price, commission_rate)
                VALUES
                  ('鐠炴偊閰掑簵', 'ctrip', 'TWIN', '2026-06-30', 'ct-prod-decimal', 'TWIN-editable', 'cipher-decimal', 1.0000, 188, 0.10)
                """
            )
            conn.commit()

        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="ctrip",
            hotel_name="鐠炴偊閰掑簵",
            room_type_name="TWIN",
            business_date="2026-06-30",
            target_sale_price=209,
            source_decision_id="DEC-CTRIP-DECIMAL",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["ctrip"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["inserted_task_count"], 1)
        self.assertEqual(result["skipped_product_count"], 0)

    def test_ctrip_decimal_string_editable_flag_is_supported(self) -> None:
        reason = _product_skip_reason(
            "ctrip",
            {
                "ota_product_id": "ct-prod-decimal-string",
                "product_cipher": "cipher-decimal",
                "price_editable_flag": "1.0000",
            },
        )

        self.assertIsNone(reason)

    def test_duplicate_pending_task_is_skipped(self) -> None:
        kwargs = dict(
            channel_source="meituan",
            hotel_name="璞悦酒店",
            room_type_name="KING",
            ota_product_id="mt-prod-1",
            business_date="2026-06-30",
            target_sale_price=199,
            source_decision_id="DEC-001",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["meituan"],
            now="2026-06-26 10:00:00",
        )
        first = write_zhiting_price_tasks(self.db_path, **kwargs)
        second = write_zhiting_price_tasks(self.db_path, **{**kwargs, "source_decision_id": "DEC-002"})

        self.assertEqual(first["inserted_task_count"], 1)
        self.assertEqual(second["inserted_task_count"], 0)
        self.assertEqual(second["skipped_product_count"], 1)
        self.assertEqual({item["reason"] for item in second["skipped_products"]}, {"duplicate_pending_task_skipped"})

    def test_write_switch_disabled_returns_preview_without_insert(self) -> None:
        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="meituan",
            hotel_name="璞悦酒店",
            room_type_name="KING",
            ota_product_id="mt-prod-1",
            business_date="2026-06-30",
            target_sale_price=199,
            source_decision_id="DEC-001",
            created_by="owner-1",
            write_enabled=False,
            confirmed=True,
            allowed_channels=["meituan"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["write_performed"])
        self.assertEqual(result["blocked_reason"], "price_task_write_disabled")
        with contextlib.closing(connect(self.db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM meituan_zhiting_price_task").fetchone()["count"]
        self.assertEqual(count, 0)

    def test_ctrip_dry_run_preview_hides_product_cipher_plaintext(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO ctrip_ota_goods_price_mapping
                  (hotel_name, channel_source, room_type_name, business_date, ota_product_id, ota_product_name, product_cipher, price_editable_flag, ota_sale_price, commission_rate)
                VALUES
                  ('safe-demo-hotel', 'ctrip', 'SAFEKING', '2026-06-30', 'ct-safe-1', 'SAFEKING', 'cipher-safe-secret', 1, 188, 0.10)
                """
            )
            conn.commit()
        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="ctrip",
            hotel_name="safe-demo-hotel",
            room_type_name="SAFEKING",
            business_date="2026-06-30",
            target_sale_price=209,
            source_decision_id="DEC-CTRIP-DRY",
            created_by="owner-1",
            write_enabled=False,
            confirmed=True,
            allowed_channels=["ctrip"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["live_api_called"])
        self.assertTrue(result["task_rows_preview"][0]["has_product_cipher"])
        self.assertNotIn("product_cipher", result["task_rows_preview"][0])
        self.assertNotIn("cipher-safe-secret", json.dumps(result, ensure_ascii=False))
        with contextlib.closing(connect(self.db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM ctrip_zhiting_price_task").fetchone()["count"]
        self.assertEqual(count, 0)

    def test_confirmation_required_does_not_write_task(self) -> None:
        result = write_zhiting_price_tasks(
            self.db_path,
            channel_source="meituan",
            hotel_name="鐠炴偊閰掑簵",
            room_type_name="KING",
            business_date="2026-06-30",
            target_sale_price=199,
            source_decision_id="DEC-NO-CONFIRM",
            created_by="owner-1",
            write_enabled=True,
            confirmed=False,
            allowed_channels=["meituan"],
            now="2026-06-26 10:00:00",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "price_task_confirmation_required")
        self.assertFalse(result["live_api_called"])
        with contextlib.closing(connect(self.db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM meituan_zhiting_price_task").fetchone()["count"]
        self.assertEqual(count, 0)

    def test_readback_distinguishes_pending_success_and_failed(self) -> None:
        for pid in ("mt-prod-1", "mt-prod-2"):
            write_zhiting_price_tasks(
                self.db_path,
                channel_source="meituan",
                hotel_name="璞悦酒店",
                room_type_name="KING",
                ota_product_id=pid,
                business_date="2026-06-30",
                target_sale_price=199,
                source_decision_id="DEC-001",
                created_by="owner-1",
                write_enabled=True,
                confirmed=True,
                allowed_channels=["meituan"],
                now="2026-06-26 10:00:00",
            )
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE meituan_zhiting_price_task SET execute_status='FAILED', error_message='ota rejected', executed_at='2026-06-26 10:05:00' WHERE ota_product_id='mt-prod-2'"
            )
            conn.commit()

        status = read_price_task_status(self.db_path, channel_source="meituan", business_date="2026-06-30", source_decision_id="DEC-001")

        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["status_counts"], {"FAILED": 1, "PENDING": 1})
        failed = next(row for row in status["tasks"] if row["execute_status"] == "FAILED")
        self.assertEqual(failed["error_message"], "ota rejected")
        self.assertEqual(failed["executed_at"], "2026-06-26 10:05:00")

    def test_read_price_task_status_filters_by_hotel_name(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO meituan_zhiting_price_task
                  (hotel_name, ota_product_id, room_type_name, business_date, target_sale_price, execute_status, created_at)
                VALUES
                  ('酒店A', 'mt-a', 'KING', '2026-06-30', 199, 'PENDING', '2026-06-26 10:00:00'),
                  ('酒店B', 'mt-b', 'KING', '2026-06-30', 209, 'PENDING', '2026-06-26 10:00:00')
                """
            )
            conn.commit()

        status = read_price_task_status(self.db_path, channel_source="meituan", hotel_name="酒店A")

        self.assertEqual(status["status"], "ok")
        product_ids = {row["ota_product_id"] for row in status["tasks"]}
        self.assertEqual(product_ids, {"mt-a"})

    def test_price_task_history_cli_command_lists_hotel_history(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO meituan_zhiting_price_task
                  (hotel_name, ota_product_id, room_type_name, business_date, target_sale_price, execute_status, created_at)
                VALUES
                  ('酒店A', 'mt-a', 'KING', '2026-06-30', 199, 'SUCCESS', '2026-06-26 10:00:00'),
                  ('酒店B', 'mt-b', 'KING', '2026-06-30', 209, 'PENDING', '2026-06-26 10:00:00')
                """
            )
            conn.commit()

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli_main(
                ["--db", self.db_path, "price-task-history", "--channel-source", "meituan", "--hotel-name", "酒店A"]
            )

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "ok")
        product_ids = {row["ota_product_id"] for row in payload["tasks"]}
        self.assertEqual(product_ids, {"mt-a"})

    def test_readback_exposes_business_review_lifecycle_without_changing_plugin_statuses(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute("UPDATE meituan_ota_goods_price_mapping SET hotel_name=NULL")
            conn.commit()
        for pid in ("mt-prod-1", "mt-prod-2"):
            write_zhiting_price_tasks(
                self.db_path,
                channel_source="meituan",
                hotel_name="鐠炴偊閰掑簵",
                room_type_name="KING",
                ota_product_id=pid,
                business_date="2026-06-30",
                target_sale_price=199,
                source_decision_id="DEC-001",
                created_by="owner-1",
                write_enabled=True,
                confirmed=True,
                allowed_channels=["meituan"],
                now="2026-06-26 10:00:00",
            )
        with contextlib.closing(connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE meituan_zhiting_price_task SET execute_status='SUCCESS', executed_at='2026-06-26 10:05:00' WHERE ota_product_id='mt-prod-1'"
            )
            conn.execute(
                "UPDATE meituan_zhiting_price_task SET execute_status='FAILED', error_message='ota rejected', executed_at='2026-06-26 10:05:00' WHERE ota_product_id='mt-prod-2'"
            )
            conn.commit()

        status = read_price_task_status(self.db_path, channel_source="meituan", business_date="2026-06-30", source_decision_id="DEC-001")

        self.assertEqual(status["status_counts"], {"FAILED": 1, "SUCCESS": 1})
        self.assertEqual(status["lifecycle_status_counts"], {"plugin_failed": 1, "verification_pending": 1})
        success = next(row for row in status["tasks"] if row["execute_status"] == "SUCCESS")
        self.assertEqual(success["review_lifecycle_status"], "verification_pending")
        self.assertEqual(
            success["review_lifecycle_transitions"],
            ["created", "pending_review", "approved", "queued_to_plugin", "plugin_success", "verification_pending"],
        )
        failed = next(row for row in status["tasks"] if row["execute_status"] == "FAILED")
        self.assertEqual(failed["review_lifecycle_status"], "plugin_failed")
        self.assertEqual(
            failed["review_lifecycle_transitions"],
            ["created", "pending_review", "approved", "queued_to_plugin", "plugin_failed"],
        )


class TestExecutePriceOutboxCli(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self._tmp.name) / "cli.sqlite")
        with contextlib.closing(connect(self.db_path)) as conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO meituan_ota_goods_price_mapping
                  (hotel_name, channel_source, room_type_name, business_date, ota_product_id, ota_product_name, ota_sale_price, commission_rate)
                VALUES ('璞悦酒店', 'meituan', 'KING', '2026-06-30', 'mt-prod-1', 'KING-无早', 188, 0.12)
                """
            )
            conn.commit()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, args: list[str], env: dict[str, str] | None = None) -> dict:
        old_env = os.environ.copy()
        if env:
            os.environ.update(env)
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                code = cli_main(args)
            self.assertEqual(code, 0)
            return json.loads(output.getvalue())
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_execute_price_live_defaults_to_deprecated_direct_api_blocked(self) -> None:
        result = self._run(
            [
                "--db",
                self.db_path,
                "execute-price",
                "--hotel-id",
                "hotel-a",
                "--hotel-name",
                "璞悦酒店",
                "--room-type-id",
                "KING",
                "--room-type-name",
                "KING",
                "--channel-source",
                "meituan",
                "--normal-price",
                "199",
                "--business-date",
                "2026-06-30",
                "--begin-date",
                "2026-06-30",
                "--end-date",
                "2026-06-30",
                "--user-role",
                "admin",
                "--approved-by",
                "admin-1",
                "--approval-id",
                "approval-placeholder",
            ],
            env={"BEYONDH_ENABLE_LIVE": "1", "HOTEL_OTA_PRICE_TASK_WRITE_ENABLE": "0"},
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "direct_api_execution_deprecated_use_price_task_outbox")
        self.assertFalse(result["live_call"])

    def test_execute_price_uses_database_profile_dsn_env_for_price_task_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mapping_config = Path(tmp) / "database-source.json"
            mapping_config.write_text(
                json.dumps(
                    {
                        "default_profile": "puyue_mysql_prod",
                        "profiles": {
                            "puyue_mysql_prod": {
                                "db_kind": "mysql",
                                "dsn_env": "HOTEL_OTA_DB_DSN_PUYUE",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            execution = price_execution_payload(
                hotel_id="hotel-a",
                room_type_id="KING",
                channel="Mtop",
                ota_product_id="mt-product-1",
                normal_price=199.0,
                old_price=188.0,
                price_guard_policy_id="policy-1",
                begin_date="2026-06-30",
                end_date="2026-06-30",
                floor_price=150.0,
                ceiling_price=260.0,
                max_increase_pct=0.2,
                max_decrease_pct=0.2,
                min_increase_pct=0.05,
                min_decrease_pct=0.05,
                freshness_status="fresh",
                guard_version=1,
            )
            approval = {
                "approval_id": "approval-1",
                "status": "approved",
                "action_type": "price_update",
                "approved_by": "admin-1",
                "payload": {
                    **execution,
                    "business_status": "current",
                    "data_source_type": "real_database",
                    "price_guard_policy_id": "policy-1",
                    "price_guard_policy_version": 1,
                    "approved_payload_hash": price_execution_payload_hash(execution),
                },
            }

            with mock.patch(
                "runtime.decisions.pricing.resolve_price_guard_policy",
                return_value={
                    "source": "active_price_guard_policy",
                    "policy_id": "policy-1",
                    "version": 1,
                    "floor_price": 150.0,
                    "ceiling_price": 260.0,
                    "max_increase_pct": 0.2,
                    "max_decrease_pct": 0.2,
                    "min_increase_pct": 0.05,
                    "min_decrease_pct": 0.05,
                },
            ) as resolve_mock, mock.patch("runtime.decisions.pricing.approval_get", return_value=approval), mock.patch(
                "runtime.decisions.pricing.write_zhiting_price_tasks",
                return_value={"status": "queued", "inserted_task_count": 1},
            ) as write_mock:
                result = self._run(
                    [
                        "--db",
                        self.db_path,
                        "execute-price",
                        "--hotel-id",
                        "hotel-a",
                        "--hotel-name",
                        "Example Hotel",
                        "--room-type-id",
                        "KING",
                        "--room-type-name",
                        "King",
                        "--channel-source",
                        "meituan",
                        "--ota-product-id",
                        "mt-product-1",
                        "--normal-price",
                        "199",
                        "--old-price",
                        "188",
                        "--business-date",
                        "2026-06-30",
                        "--begin-date",
                        "2026-06-30",
                        "--end-date",
                        "2026-06-30",
                        "--user-role",
                        "admin",
                        "--approved-by",
                        "admin-1",
                        "--approver-role",
                        "admin",
                        "--approval-id",
                        "approval-1",
                    ],
                    env={
                        "BEYONDH_ENABLE_LIVE": "1",
                        "HOTEL_OTA_PRICE_TASK_WRITE_ENABLE": "1",
                        "HOTEL_OTA_DB_KIND": "mysql",
                        "HOTEL_OTA_DB_MAPPING_CONFIG": str(mapping_config),
                        "HOTEL_OTA_DB_PROFILE": "puyue_mysql_prod",
                        "HOTEL_OTA_DB_DSN_PUYUE": "mysql+pymysql://user:pass@127.0.0.1:13306/hotel_puyue",
                    },
                )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(write_mock.call_args.kwargs["dsn"], "mysql+pymysql://user:pass@127.0.0.1:13306/hotel_puyue")
        self.assertEqual(
            resolve_mock.call_args.kwargs["ota_product_id"],
            "mt-product-1",
        )
        self.assertFalse(result["live_api_called"])

    def test_legacy_beyondh_call_live_is_deprecated_and_blocked(self) -> None:
        result = self._run(
            [
                "--db",
                self.db_path,
                "beyondh-call",
                "--hotel-id",
                "hotel-a",
                "--method",
                "Price.SetPriceByRoomTypeId",
                "--biz-content",
                '{"roomTypeId":"KING","price":199}',
                "--no-log",
            ],
            env={"BEYONDH_ENABLE_LIVE": "1"},
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "direct_api_execution_deprecated_use_price_task_outbox")
        self.assertEqual(result["direct_api_execution_status"], "deprecated")
        self.assertFalse(result["live_call"])
        self.assertFalse(result["live_api_called"])

    def test_env_check_reports_price_task_and_direct_api_status(self) -> None:
        result = self._run(
            ["--db", self.db_path, "env-check"],
            env={
                "HOTEL_OTA_ENV": "production",
                "HOTEL_OTA_FEISHU_DEBUG": "0",
                "HOTEL_OTA_FEISHU_FINAL_GATE_REQUIRED": "1",
                "HOTEL_OTA_FEISHU_ALLOW_FILE_EXPORT": "0",
                "HOTEL_OTA_FEISHU_ALLOW_CONFIG_EXPORT": "0",
                "HOTEL_OTA_FEISHU_ALLOW_RAW_DATA_EXPORT": "0",
                "HOTEL_OTA_PRICE_TASK_WRITE_ENABLE": "1",
                "HOTEL_OTA_PRICE_TASK_REQUIRE_CONFIRM": "1",
                "HOTEL_OTA_PRICE_TASK_ALLOWED_CHANNELS": "ctrip,meituan",
                "BEYONDH_ENABLE_LIVE": "0",
                "MEITUAN_ENABLE_LIVE": "0",
                "DINDANLL_ENABLE_LIVE": "0",
            },
        )

        self.assertEqual(result["direct_api_execution_status"], "deprecated_disabled_safe")
        self.assertEqual(result["price_task_write_status"], "enabled")
        self.assertTrue(result["price_task_outbox_status"]["ready_for_task_write"])


if __name__ == "__main__":
    unittest.main()
