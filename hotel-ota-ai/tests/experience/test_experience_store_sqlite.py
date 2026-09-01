from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.experience.experience_candidate import build_candidate_from_runtime_result
from runtime.experience.experience_store import find_candidate, list_candidates, upsert_candidate
from runtime.experience.experience_reviewer import review_candidate
from runtime.storage import connect, init_schema


class TestExperienceStoreSqlite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self.tmp.name) / "experience.sqlite")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_init_schema_creates_experience_candidates_table(self) -> None:
        with closing(connect(self.db_path)) as conn:
            init_schema(conn)
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'experience_candidates'"
            ).fetchone()
        self.assertIsNotNone(row)

    def test_sqlite_store_filters_candidates_by_hotel_id(self) -> None:
        first = build_candidate_from_runtime_result({"run_id": "r1", "data_source_type": "fresh_real_data"})
        second = build_candidate_from_runtime_result({"run_id": "r2", "data_source_type": "fresh_real_data"})
        upsert_candidate(first, db_path=self.db_path, hotel_id="hotel-a")
        upsert_candidate(second, db_path=self.db_path, hotel_id="hotel-b")

        candidates = list_candidates(db_path=self.db_path, hotel_id="hotel-a")
        self.assertEqual([item["candidate_id"] for item in candidates], [first["candidate_id"]])
        self.assertEqual(candidates[0]["storage_mode"], "sqlite_runtime")

    def test_explicit_json_store_remains_fallback_source(self) -> None:
        path = Path(self.tmp.name) / "experience.json"
        path.write_text(
            json.dumps({"candidates": [{"candidate_id": "json-1", "hotel_id": "hotel-a"}]}),
            encoding="utf-8",
        )
        self.assertEqual(find_candidate("json-1", path, hotel_id="hotel-a")["candidate_id"], "json-1")

    def test_reviewed_candidate_is_persisted_back_to_sqlite(self) -> None:
        candidate = build_candidate_from_runtime_result(
            {"run_id": "r1", "data_source_type": "fresh_real_data", "summary": "conversion mapping improved"}
        )
        candidate["no_incremental_value"] = False
        upsert_candidate(candidate, db_path=self.db_path, hotel_id="hotel-a")
        reviewed = review_candidate(candidate, approve=True, reviewer="owner")["candidate"]
        upsert_candidate(reviewed, db_path=self.db_path, hotel_id="hotel-a")

        stored = find_candidate(candidate["candidate_id"], hotel_id="hotel-a", db_path=self.db_path)
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(stored["reviewed_by"], "owner")
        self.assertFalse(stored["approval_data_allowed"])
        self.assertFalse(stored["live_allowed"])


if __name__ == "__main__":
    unittest.main()
