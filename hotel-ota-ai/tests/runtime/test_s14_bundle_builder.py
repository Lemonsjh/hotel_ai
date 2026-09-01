from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.capability_results import (
    build_versioned_capability_result,
    find_latest_capability_result,
    save_capability_result,
)
from runtime.cli import main
from runtime.s14_bundle_builder import (
    build_and_run_s14,
    is_s14_operation_message,
)
from runtime.storage import connect, init_schema


class TestS14BundleBuilder(unittest.TestCase):
    def _db(self, root: Path) -> str:
        db_path = str(root / "runtime.sqlite")
        conn = connect(db_path)
        try:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO hotels (
                    hotel_id, name, org_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "puyue",
                    "璞悦",
                    "org-puyue",
                    "2026-08-03T15:00:00+08:00",
                    "2026-08-03T15:00:00+08:00",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return db_path

    @staticmethod
    def _runner(capability_id: str, context: dict) -> dict:
        del context
        return {
            "status": "data_gap" if capability_id == "S10" else "ok",
            "skill_id": capability_id,
            "summary": f"{capability_id} result",
            "evidence": {"source": capability_id},
        }

    def test_init_schema_adds_capability_and_s14_result_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(Path(tmp))
            conn = sqlite3.connect(db_path)
            try:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                conn.close()

        self.assertIn("capability_results", tables)
        self.assertIn("s14_diagnosis_runs", tables)

    def test_builder_runs_all_capabilities_and_returns_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(Path(tmp))
            result = build_and_run_s14(
                organization_id=None,
                hotel_id="puyue",
                target_business_date="2026-08-03",
                as_of_datetime="2026-08-03T15:30:00+08:00",
                db_path=db_path,
                capability_runner=self._runner,
            )

        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["result_persisted"])
        self.assertEqual(result["capability_result_count"], 10)
        self.assertEqual(
            result["capability_collection_summary"]["generated_count"], 10
        )
        self.assertEqual(
            result["capability_collection_summary"]["degraded_count"], 1
        )
        self.assertTrue(
            any(
                item["issue_code"] == "capability_status:S10:data_gap"
                for item in result["items"]
            )
        )

    def test_saved_results_are_reused_without_rerunning_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(Path(tmp))
            first = build_and_run_s14(
                organization_id="org-puyue",
                hotel_id="puyue",
                target_business_date="2026-08-03",
                as_of_datetime="2026-08-03T15:30:00+08:00",
                db_path=db_path,
                capability_runner=self._runner,
            )

            def must_not_run(capability_id: str, context: dict) -> dict:
                raise AssertionError(f"unexpected rerun: {capability_id}")

            second = build_and_run_s14(
                organization_id="org-puyue",
                hotel_id="puyue",
                target_business_date="2026-08-03",
                as_of_datetime="2026-08-03T15:30:00+08:00",
                db_path=db_path,
                capability_runner=must_not_run,
            )

        self.assertEqual(
            first["capability_collection_summary"]["generated_count"], 10
        )
        self.assertEqual(
            second["capability_collection_summary"]["saved_count"], 10
        )

    def test_refresh_creates_new_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(Path(tmp))
            kwargs = {
                "organization_id": "org-puyue",
                "hotel_id": "puyue",
                "target_business_date": "2026-08-03",
                "as_of_datetime": "2026-08-03T15:30:00+08:00",
                "db_path": db_path,
                "capability_runner": self._runner,
            }
            build_and_run_s14(**kwargs)
            build_and_run_s14(**kwargs, refresh=True)
            latest = find_latest_capability_result(
                db_path=db_path,
                organization_id="org-puyue",
                hotel_id="puyue",
                capability_id="S2",
                target_business_date="2026-08-03",
                as_of_datetime="2026-08-03T15:30:00+08:00",
                contract_revision="diagnosis-contract.v1",
                policy_revision="diagnosis-default.v1",
            )

        self.assertIsNotNone(latest)
        self.assertEqual(latest["result_version"], 2)

    def test_cli_no_longer_requires_source_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(Path(tmp))
            output = io.StringIO()
            with mock.patch(
                "runtime.s14_bundle_builder.run_capability_via_cli",
                side_effect=self._runner,
            ), contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "--db",
                        db_path,
                        "s14-diagnosis",
                        "--hotel-id",
                        "puyue",
                        "--date",
                        "2026-08-03",
                        "--as-of-datetime",
                        "2026-08-03T15:30:00+08:00",
                    ]
                )
            payload = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["skill_id"], "S14")
        self.assertEqual(payload["status"], "partial")
        self.assertNotIn("source_mode", payload)
        self.assertTrue(payload["result_persisted"])

    def test_message_routing_separates_formal_s14_from_demo_and_ext(self) -> None:
        self.assertTrue(is_s14_operation_message("本店OTA运营诊断"))
        self.assertTrue(is_s14_operation_message("跑一下 S14"))
        self.assertFalse(is_s14_operation_message("跑一下 S14 演示"))
        self.assertFalse(is_s14_operation_message("运行 S14-EXT source=monthly_excel"))

    def test_blank_org_id_uses_exact_hotel_scope_without_blocking_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(Path(tmp))
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("UPDATE hotels SET org_id='' WHERE hotel_id='puyue'")
                conn.commit()
            finally:
                conn.close()

            def all_ok(capability_id: str, context: dict) -> dict:
                del context
                return {
                    "status": "ok",
                    "skill_id": capability_id,
                    "summary": f"{capability_id} result",
                    "evidence": {"source": capability_id},
                }

            result = build_and_run_s14(
                organization_id=None,
                hotel_id="puyue",
                target_business_date="2026-08-03",
                as_of_datetime="2026-08-03T15:30:00+08:00",
                db_path=db_path,
                capability_runner=all_ok,
            )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["organization_resolution_source"],
            "derived_exact_hotel_scope",
        )
        self.assertIn(
            "organization_id_derived_from_exact_hotel_scope",
            result["data_limitations"],
        )

    def test_reference_only_capability_is_saved_as_data_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(Path(tmp))

            def runner(capability_id: str, context: dict) -> dict:
                del context
                if capability_id == "S8":
                    return {
                        "status": "ok",
                        "skill_id": "S8",
                        "summary": "reference only",
                        "evidence": {"api_status": "reference_only"},
                    }
                return {
                    "status": "ok",
                    "skill_id": capability_id,
                    "summary": capability_id,
                    "evidence": {"source": capability_id},
                }

            result = build_and_run_s14(
                organization_id="org-puyue",
                hotel_id="puyue",
                target_business_date="2026-08-03",
                as_of_datetime="2026-08-03T15:30:00+08:00",
                db_path=db_path,
                capability_runner=runner,
            )

        s8 = next(
            item
            for item in result["capability_collection"]
            if item["capability_id"] == "S8"
        )
        self.assertEqual(s8["status"], "data_gap")
        self.assertEqual(result["status"], "partial")

    def test_result_store_rejects_future_capture_for_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db(Path(tmp))
            result = build_versioned_capability_result(
                capability_id="S2",
                raw_result={"status": "ok", "summary": "future"},
                organization_id="org-puyue",
                hotel_id="puyue",
                target_business_date="2026-08-03",
                as_of_datetime="2026-08-03T16:00:00+08:00",
                captured_at="2026-08-03T16:00:00+08:00",
            )
            save_capability_result(result, db_path=db_path)
            found = find_latest_capability_result(
                db_path=db_path,
                organization_id="org-puyue",
                hotel_id="puyue",
                capability_id="S2",
                target_business_date="2026-08-03",
                as_of_datetime="2026-08-03T15:30:00+08:00",
                contract_revision="diagnosis-contract.v1",
                policy_revision="diagnosis-default.v1",
            )

        self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
