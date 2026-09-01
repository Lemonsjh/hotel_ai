from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.adapters import database
from runtime.adapters.nearby_events import load_database_nearby_events
from runtime.market_sources import build_event_context


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "database-source.example.json"


EXPECTED_TABLES = {
    "daily_metrics": "jy01_hotel_statistics_daily",
    "monthly_metrics": "jy03_hotel_statistics_month",
    "reservation_snapshot": "jd01_booking_detail",
    "stayover_snapshot": "jd04_inhouse_extension",
    "room_status_snapshot": "kf11_room_status_snapshot",
    "pms_room_type_forecast": "pms_room_type_forecast",
    "pms_room_type_hourly_status": "pms_room_type_hourly_status",
    "room_fee_daily": "rs01_room_revenue_daily",
    "meituan_scan_order_detail": "meituan_ota_scan_order_detail",
    "meituan_user_source_monthly": "meituan_ota_user_source_monthly",
    "ctrip_order_detail": "ctrip_ota_order_detail",
    "ctrip_userprofile_distribution": "ctrip_ota_userprofile_distribution",
    "meituan_order_loss_monthly": "meituan_ota_order_loss_monthly",
    "ctrip_order_loss_monthly": "ctrip_ota_order_loss_monthly",
    "ctrip_competition_metrics_30d": "ctrip_ota_competition_metrics_30d",
    "room_type_classification": "jl11_room_type_classification",
    "room_type_mapping": "hotel_room_type_mapping",
    "ctrip_business_metrics": "ctrip_ota_business_metrics",
    "meituan_business_metrics": "meituan_ota_business_metrics",
    "ctrip_price_mapping": "ctrip_ota_goods_price_mapping",
    "meituan_price_mapping": "meituan_ota_goods_price_mapping",
    "ctrip_promotion_activity": "ctrip_ota_promotion_activity",
    "meituan_promotion_activity": "meituan_ota_promotion_activity",
    "ctrip_promotion_performance_30d": "ctrip_ota_promotion_performance_30d",
    "meituan_promotion_performance_30d": "meituan_ota_promotion_performance_30d",
    "ctrip_activity_product_detail": "ctrip_ota_activity_product_detail",
    "meituan_activity_product_detail": "meituan_ota_activity_product_detail",
    "ctrip_joined_rights": "ctrip_ota_joined_rights",
    "meituan_joined_rights": "meituan_ota_joined_rights",
    "ctrip_psi_metric": "ctrip_ota_psi_metric",
    "ctrip_psi_score": "ctrip_ota_psi_score",
    "ctrip_review_detail": "ctrip_ota_review_detail",
    "meituan_review_detail": "meituan_ota_review_detail",
    "ctrip_review_overview": "ctrip_ota_review_overview",
    "meituan_review_overview": "meituan_ota_review_overview",
    "ctrip_review_ranking": "ctrip_ota_review_ranking",
    "meituan_review_ranking": "meituan_ota_review_ranking",
    "meituan_nearby_event": "meituan_ota_nearby_event",
    "ctrip_price_task": "ctrip_price_task",
    "meituan_price_task": "meituan_price_task",
}


class TestDatabaseSourceV4Mapping(unittest.TestCase):
    def _config(self) -> dict:
        return json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_room_mapping_schema_drift_does_not_block_optional_enrichment(self) -> None:
        class FailingCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params):
                raise RuntimeError("Unknown column 'hotel_name' in 'field list'")

        class FailingConnection:
            def cursor(self):
                return FailingCursor()

        profile = {
            "tables": {"room_type_mapping": "hotel_room_type_mapping"},
            "columns": {
                "room_type_mapping": {
                    "hotel_id": "hotel_id",
                    "hotel_name": "hotel_name",
                    "room_type_id": "room_type_id",
                    "room_type_name": "room_type_name",
                }
            },
        }

        rows = database._load_room_mapping_rows(
            FailingConnection(),
            argparse.Namespace(hotel_id="puyue", source_platform=None),
            profile,
        )

        self.assertEqual(rows, [])

    def test_example_uses_puyue_profile_and_pms_forecast_mapping(self) -> None:
        config = self._config()
        self.assertEqual(config["version"], 3)
        self.assertEqual(config["default_profile"], "puyue_mysql_prod")
        profile = config["profiles"]["puyue_mysql_prod"]
        self.assertEqual(profile["dsn_env"], "HOTEL_OTA_DB_DSN_PUYUE")
        self.assertEqual(profile["mapping_version"], "puyue_pms_forecast_20260803_v3")
        self.assertEqual(profile["tables"], EXPECTED_TABLES)

    def test_meituan_monthly_loss_mapping_covers_competition_circle_aggregation(self) -> None:
        columns = self._config()["profiles"]["puyue_mysql_prod"]["columns"]["meituan_order_loss_monthly"]

        self.assertEqual(
            {key: columns[key] for key in ("competitor_poi_id", "competitor_circle_name", "competitor_loss_order_count", "competitor_loss_amount")},
            {
                "competitor_poi_id": "competitor_poi_id",
                "competitor_circle_name": "competitor_circle_name",
                "competitor_loss_order_count": "competitor_loss_order_count",
                "competitor_loss_amount": "competitor_loss_amount",
            },
        )

    def test_example_documents_hotel_alias_list_without_real_tenant_aliases(self) -> None:
        profile = self._config()["profiles"]["puyue_mysql_prod"]
        hotel = profile["hotel_ids"]["example-hotel"]

        self.assertEqual(hotel["hotel_name"], "Example Hotel")
        self.assertEqual(hotel["display_name"], "Example")
        self.assertEqual(hotel["aliases"], ["Example Hotel Alias", "Example Short Name"])
        self.assertNotIn("puyue", json.dumps(hotel, ensure_ascii=False).lower())
        self.assertNotIn("璞悦", json.dumps(hotel, ensure_ascii=False))

    def test_example_does_not_reference_legacy_fact_or_report_tables(self) -> None:
        text = CONFIG.read_text(encoding="utf-8")
        for forbidden in (
            "report_mysql_prod",
            "fact_daily_metrics",
            "fact_monthly_metrics",
            "fact_room_fee_daily",
            "fact_room_status_snapshot",
            "operating_snapshot",
            "price_data",
            "demand_context",
        ):
            self.assertNotIn(forbidden, text)

    def test_core_columns_use_source_platform_and_horizontal_jy_tables(self) -> None:
        profile = self._config()["profiles"]["puyue_mysql_prod"]
        columns = profile["columns"]
        for key in (
            "daily_metrics",
            "monthly_metrics",
            "reservation_snapshot",
            "stayover_snapshot",
            "room_status_snapshot",
            "room_fee_daily",
        ):
            self.assertEqual(columns[key]["hotel_name"], "hotel_name")
            self.assertEqual(columns[key]["hotel_id"], "hotel_id")
            self.assertEqual(columns[key]["source_platform"], "source_platform")
            self.assertEqual(columns[key]["snapshot_time"], "snapshot_time")
        self.assertEqual(columns["daily_metrics"]["occupancy_rate"], "occupancy_rate")
        self.assertEqual(columns["daily_metrics"]["sold_rooms"], "sold_rooms")
        self.assertEqual(columns["pms_room_type_forecast"]["overbooking_rooms"], "overbooking_rooms")
        self.assertEqual(columns["pms_room_type_hourly_status"]["snapshot_hour"], "snapshot_hour")
        self.assertNotIn("stats_period_type", columns["ctrip_business_metrics"])
        self.assertNotIn("period_days", columns["meituan_business_metrics"])
        self.assertEqual(columns["meituan_activity_product_detail"]["ota_product_id"], "ota_product_id")
        self.assertEqual(columns["meituan_activity_product_detail"]["room_type_id"], "room_type_id")
        self.assertEqual(columns["meituan_promotion_performance_30d"]["spend_amount"], "spend_amount")
        self.assertEqual(columns["ctrip_promotion_performance_30d"]["booking_order_amount"], "booking_order_amount")
        self.assertEqual(columns["monthly_metrics"]["room_revenue"], "room_revenue")
        self.assertEqual(columns["ctrip_price_mapping"]["product_cipher"], "product_cipher")
        self.assertEqual(columns["room_type_mapping"]["source_product_id"], "source_product_id")
        self.assertEqual(columns["room_type_mapping"]["mapping_status"], "mapping_status")
        self.assertEqual(columns["meituan_price_task"]["execute_status"], "execute_status")
        self.assertEqual(columns["reservation_snapshot"]["arrival_time"], "arrival_time")
        self.assertEqual(columns["room_fee_daily"]["order_id"], "order_id")
        self.assertEqual(columns["room_fee_daily"]["room_type_name"], "room_type_name")
        self.assertEqual(columns["room_fee_daily"]["room_daily_price"], "room_daily_price")
        self.assertEqual(columns["meituan_nearby_event"]["event_id"], "event_id")
        self.assertEqual(columns["meituan_nearby_event"]["event_start_date"], "event_start_date")
        self.assertEqual(columns["meituan_nearby_event"]["hotel_name"], "hotel_name")
        self.assertNotIn("hotel_name", columns["ctrip_price_mapping"])
        self.assertNotIn("hotel_name", columns["meituan_price_mapping"])
        self.assertEqual(columns["ctrip_price_mapping"]["hotel_id"], "hotel_id")
        self.assertEqual(columns["meituan_price_mapping"]["hotel_id"], "hotel_id")
        self.assertEqual(columns["ctrip_price_mapping"]["channel_source"], "channel_source")
        self.assertEqual(columns["meituan_price_mapping"]["channel_source"], "channel_source")

    def test_runtime_allows_zhiting_v4_controlled_templates(self) -> None:
        expected_templates = set(self._config()["allowed_templates"])
        self.assertTrue(expected_templates.issubset(set(database.TEMPLATES)))
        self.assertIn("price_snapshot", database.TEMPLATES)
        self.assertIn("order_snapshot", database.TEMPLATES)

    def test_price_snapshot_prefers_v4_ota_price_mapping(self) -> None:
        profile = self._config()["profiles"]["puyue_mysql_prod"]
        self.assertTrue(database._has_any_template_mapping(profile, database.V4_TEMPLATE_TABLE_KEYS["ota_price_mapping"]))
        self.assertFalse(database._has_template_mapping(profile, "price_data"))

    def test_unversioned_openclaw_views_are_flagged(self) -> None:
        profile = {
            "tables": {"daily_metrics": "v_openclaw_operating_snapshot"},
            "columns": {"daily_metrics": {"hotel_name": "hotel_name"}},
        }
        self.assertEqual(database._view_migration_risks(profile), ["view_migration_untracked"])
        profile["view_migration_version"] = "20260626_manual_reviewed"
        self.assertEqual(database._view_migration_risks(profile), [])

    def test_database_source_metadata_declares_runtime_and_blocks_downstream(self) -> None:
        source = database._source("mysql")
        self.assertEqual(source["source_mode"], "mysql_runtime")
        self.assertEqual(source["data_source_label"], "mysql_runtime")
        self.assertEqual(source["source_capability"], "read_only")
        self.assertFalse(source["approval_allowed"])
        self.assertFalse(source["live_allowed"])
        self.assertFalse(source["downstream_allowed"])
        self.assertEqual(source["downstream_blocked_reason"], "database_read_only_runtime")

    def test_database_source_metadata_preserves_profile_capability_without_enabling_live(self) -> None:
        source = database._source("mysql", profile={"source_capability": "write_live_pending"})
        self.assertEqual(source["source_capability"], "write_live_pending")
        self.assertFalse(source["approval_allowed"])
        self.assertFalse(source["live_allowed"])
        self.assertFalse(source["downstream_allowed"])
        self.assertEqual(source["downstream_blocked_reason"], "database_write_pending_runtime")

    def test_database_inspect_static_metadata_flags_unversioned_openclaw_views(self) -> None:
        profile = {
            "_profile_name": "legacy_view_profile",
            "tables": {"daily_metrics": "v_openclaw_operating_snapshot"},
            "columns": {"daily_metrics": {"hotel_name": "hotel_name"}},
        }

        metadata = database._inspect_profile_metadata(profile)

        self.assertEqual(metadata["profile"], "legacy_view_profile")
        self.assertEqual(metadata["risk_flags"], ["view_migration_untracked"])
        self.assertEqual(metadata["source_capability"], "read_only")

    def test_database_inspect_table_readiness_exposes_production_summary_fields(self) -> None:
        summary = database._inspect_table_readiness(
            table_name="meituan_ota_nearby_event",
            column_names=[
                "hotel_name",
                "source_platform",
                "event_id",
                "event_start_date",
                "event_end_date",
                "snapshot_time",
            ],
            row_count_estimate=2,
            latest_business_date=None,
            updated_at="2026-06-29 12:19:17",
        )

        for key in (
            "table_name",
            "has_hotel_id",
            "has_hotel_name",
            "has_room_type_id",
            "has_room_type_name",
            "has_source_platform",
            "has_source_room_type_id",
            "has_source_product_id",
            "has_business_date",
            "latest_business_date",
            "row_count_estimate",
            "data_status",
        ):
            self.assertIn(key, summary)
        self.assertEqual(summary["table_name"], "meituan_ota_nearby_event")
        self.assertFalse(summary["has_hotel_id"])
        self.assertTrue(summary["has_hotel_name"])
        self.assertTrue(summary["has_source_platform"])
        self.assertFalse(summary["has_business_date"])
        self.assertEqual(summary["data_status"], "partial")
        self.assertIn("hotel_name_legacy", summary["risk_flags"])

    def test_database_inspect_date_candidates_do_not_treat_type_fields_as_dates(self) -> None:
        self.assertFalse(database._is_inspect_date_candidate("checkin_type"))
        self.assertFalse(database._is_inspect_date_candidate("period_days"))
        self.assertTrue(database._is_inspect_date_candidate("business_date"))
        self.assertTrue(database._is_inspect_date_candidate("snapshot_time"))

    def test_mysql_dsn_parser_accepts_unescaped_at_in_password(self) -> None:
        params = database._parse_mysql_dsn(
            "mysql+pymysql://hotel_readonly:examplePass@withAt@127.0.0.1:13306/hotel_puyue?charset=utf8mb4"
        )

        self.assertEqual(params["host"], "127.0.0.1")
        self.assertEqual(params["port"], 13306)
        self.assertEqual(params["user"], "hotel_readonly")
        self.assertEqual(params["password"], "examplePass@withAt")
        self.assertEqual(params["database"], "hotel_puyue")

    def test_source_platform_filter_uses_profile_aliases(self) -> None:
        profile = {"platform_aliases": {"meituan": ["美团", "meituan", "美团EBK"]}}
        columns = {"source_platform": "source_platform"}

        clause, params = database._source_platform_filter_clause(profile, columns, "meituan")

        self.assertIn("source_platform", clause)
        self.assertEqual(params, ["美团", "meituan", "美团EBK"])

    def test_pms_platform_filter_treats_empty_platform_as_walkin(self) -> None:
        clause, params = database._source_platform_filter_clause({}, {"source_platform": "source_platform"}, "pms")

        self.assertIn("source_platform", clause)
        self.assertIn("IS NULL", clause)
        self.assertIn("TRIM(`source_platform`) = ''", clause)
        self.assertEqual(params, ["pms", "walkin", "散客"])

    def test_sensitive_field_redaction_uses_profile_privacy_list(self) -> None:
        profile = {"privacy": {"redact_fields": ["ota_product_id"]}}

        row = database._redact_sensitive_fields(
            {"room_type_name": "KING", "ota_product_id": "product-123456", "guest_name": "private"},
            profile,
        )

        self.assertEqual(row["room_type_name"], "KING")
        self.assertNotEqual(row["ota_product_id"], "product-123456")
        self.assertNotEqual(row["guest_name"], "private")

    def test_public_review_body_fields_are_not_masked_by_profile_privacy_list(self) -> None:
        profile = {"privacy": {"redact_fields": ["review_text", "review_content", "comment_content", "comment", "product_cipher"]}}

        row = database._redact_sensitive_fields(
            {
                "review_text": "房间卫生一般，晚上有点吵，希望改进。",
                "review_content": "前台响应慢，但位置方便。",
                "comment_content": "空调声音偏大。",
                "comment": "早餐不错。",
                "guest_name": "张三",
                "phone": "13800138000",
                "order_id": "ORDER-123456",
                "room_no": "1208",
                "operator_name": "李四",
                "product_cipher": "cipher-secret",
            },
            profile,
        )

        self.assertEqual(row["review_text"], "房间卫生一般，晚上有点吵，希望改进。")
        self.assertEqual(row["review_content"], "前台响应慢，但位置方便。")
        self.assertEqual(row["comment_content"], "空调声音偏大。")
        self.assertEqual(row["comment"], "早餐不错。")
        for key in ("guest_name", "phone", "order_id", "room_no", "operator_name", "product_cipher"):
            self.assertNotIn(row[key], {"张三", "13800138000", "ORDER-123456", "1208", "李四", "cipher-secret"})

    def test_template_source_metadata_is_safe_and_readonly(self) -> None:
        metadata = database._template_source_metadata(
            template="ota_price_mapping",
            table="meituan_ota_goods_price_mapping",
            platform_key="meituan",
            raw_row_count=3,
            filtered_row_count=2,
            data_business_date="2026-06-26",
            data_snapshot_time="2026-06-26 10:00:00",
        )

        self.assertEqual(metadata["source_table"], "meituan_ota_goods_price_mapping")
        self.assertEqual(metadata["source_platform"], "meituan")
        self.assertEqual(metadata["raw_row_count"], 3)
        self.assertEqual(metadata["filtered_row_count"], 2)
        self.assertFalse(metadata["free_sql_allowed"])
        self.assertFalse(metadata["write_performed"])

    def test_database_nearby_event_marks_hotel_name_legacy_scope(self) -> None:
        class Cursor:
            def execute(self, sql, params):
                self.sql = sql
                self.params = params

            def fetchall(self):
                return [
                    {
                        "snapshot_time": "2026-06-29 12:19:17",
                        "channel_source": "meituan",
                        "hotel_name": "Example Hotel",
                        "poi_id": "poi-1",
                        "event_id": "evt-1",
                        "event_class_id": "concert",
                        "event_name": "Local Event",
                        "event_start_date": "2026-06-30",
                        "event_end_date": "2026-06-30",
                        "event_address": "Nearby Venue",
                        "distance_km": 3.5,
                        "countdown_days": 1,
                    }
                ]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class Conn:
            def cursor(self):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            mapping_path = Path(tmp) / "database-source.json"
            mapping_path.write_text(
                json.dumps(
                    {
                        "default_profile": "prod",
                        "profiles": {
                            "prod": {
                                "db_kind": "mysql",
                                "dsn": "mysql://user:pass@example.invalid/db",
                                "hotel_ids": {"hotel-a": {"hotel_name": "Example Hotel"}},
                                "tables": {"meituan_nearby_event": "meituan_ota_nearby_event"},
                                "columns": {"meituan_nearby_event": {}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "events": {
                    "enabled": True,
                    "provider": "database_nearby_event",
                    "mapping_config": str(mapping_path),
                    "profile": "prod",
                    "table_key": "meituan_nearby_event",
                }
            }
            with mock.patch.dict(os.environ, {"HOTEL_OTA_DB_SOURCE_ENABLE": "1"}, clear=False), mock.patch(
                "runtime.adapters.nearby_events._connect_mysql", return_value=Conn()
            ):
                events, meta = load_database_nearby_events(config, hotel_id="hotel-a", business_date="2026-06-29")

        self.assertEqual(len(events), 1)
        self.assertEqual(meta["tenant_filter_mode"], "hotel_name_legacy")
        self.assertIn("hotel_id_missing_in_event_table", meta["risk_flags"])
        self.assertFalse(meta["direct_price_trigger_allowed"])

    def test_database_nearby_event_prefers_hotel_id_when_available(self) -> None:
        class Cursor:
            def execute(self, sql, params):
                self.sql = sql
                self.params = params

            def fetchall(self):
                return [
                    {
                        "snapshot_time": "2026-06-30 17:57:29",
                        "channel_source": "美团",
                        "hotel_name": "Example Hotel",
                        "poi_id": "poi-1",
                        "event_id": "evt-1",
                        "event_class_id": "concert",
                        "event_name": "Local Event",
                        "event_start_date": "2026-07-01",
                        "event_end_date": "2026-07-01",
                        "event_address": "Nearby Venue",
                        "distance_km": 3.5,
                        "countdown_days": 1,
                    }
                ]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class Conn:
            cursor_obj = Cursor()

            def cursor(self):
                return self.cursor_obj

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        conn = Conn()
        with tempfile.TemporaryDirectory() as tmp:
            mapping_path = Path(tmp) / "database-source.json"
            mapping_path.write_text(
                json.dumps(
                    {
                        "default_profile": "prod",
                        "profiles": {
                            "prod": {
                                "db_kind": "mysql",
                                "dsn": "mysql://user:pass@example.invalid/db",
                                "hotel_ids": {"hotel-a": {"hotel_name": "Example Hotel"}},
                                "tables": {"meituan_nearby_event": "meituan_ota_nearby_event"},
                                "columns": {"meituan_nearby_event": {"hotel_id": "hotel_id"}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "events": {
                    "enabled": True,
                    "provider": "database_nearby_event",
                    "mapping_config": str(mapping_path),
                    "profile": "prod",
                    "table_key": "meituan_nearby_event",
                }
            }
            with mock.patch.dict(os.environ, {"HOTEL_OTA_DB_SOURCE_ENABLE": "1"}, clear=False), mock.patch(
                "runtime.adapters.nearby_events._connect_mysql", return_value=conn
            ):
                events, meta = load_database_nearby_events(config, hotel_id="hotel-a", business_date="2026-06-30")

        self.assertEqual(len(events), 1)
        self.assertEqual(meta["tenant_filter_mode"], "hotel_id")
        self.assertNotIn("hotel_id_missing_in_event_table", meta["risk_flags"])
        self.assertIn("`hotel_id` = %s", conn.cursor_obj.sql)
        self.assertEqual(conn.cursor_obj.params[0], "hotel-a")

    def test_event_context_exposes_database_tenant_filter_metadata(self) -> None:
        config = {
            "status": "ok",
            "hotels": {
                "hotel-a": {
                    "events": {
                        "enabled": True,
                        "provider": "database_nearby_event",
                    }
                }
            }
        }
        with mock.patch(
            "runtime.market_sources.load_database_nearby_events",
            return_value=(
                [{"event_id": "evt-1", "expected_heat": "medium"}],
                {
                    "status": "partial",
                    "source": "database_nearby_event",
                    "event_source": "meituan_ota_nearby_event",
                    "tenant_filter_mode": "hotel_name_legacy",
                    "risk_flags": ["hotel_id_missing_in_event_table"],
                    "data_status": "partial",
                },
            ),
        ):
            context = build_event_context(config, business_date="2026-06-30", hotel_id="hotel-a")

        self.assertEqual(context["tenant_filter_mode"], "hotel_name_legacy")
        self.assertIn("hotel_id_missing_in_event_table", context["risk_flags"])
        self.assertEqual(context["data_status"], "partial")


if __name__ == "__main__":
    unittest.main()
