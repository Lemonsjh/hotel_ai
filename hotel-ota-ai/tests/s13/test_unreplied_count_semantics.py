from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.s13.contracts import RequestContext, ReviewRecord
from runtime.s13.feishu import _render
from runtime.s13.repository import S13ControlRepository
from runtime.s13.service import S13Service
from runtime.s13.source import MemoryReviewSourceRepository, MySQLReviewSourceRepository, normalize_platform
from runtime.s13.task_outbox import SQLiteReviewTaskOutbox


NOW = datetime(2026, 8, 3, 16, 0, tzinfo=timezone.utc)


class UnrepliedCountSemanticsTests(unittest.TestCase):
    def _records(self) -> list[ReviewRecord]:
        return [
            # The latest snapshot is replied, so this review must not be counted.
            ReviewRecord(
                "hotel-a", "meituan", "m-1", "旧状态未回复", 3, False,
                "2026-08-03T10:00:00+00:00", "2026-08-02T10:00:00+00:00",
            ),
            ReviewRecord(
                "hotel-a", "meituan", "m-1", "最新状态已回复", 3, True,
                "2026-08-03T11:00:00+00:00", "2026-08-02T10:00:00+00:00",
            ),
            # The latest snapshot is unreplied, so this review must be counted once.
            ReviewRecord(
                "hotel-a", "meituan", "m-2", "旧状态已回复", 4, True,
                "2026-08-03T10:00:00+00:00", "2026-08-02T11:00:00+00:00",
            ),
            ReviewRecord(
                "hotel-a", "meituan", "m-2", "最新状态未回复", 4, False,
                "2026-08-03T12:00:00+00:00", "2026-08-02T11:00:00+00:00",
            ),
            # Pure-rating reviews are valid unreplied detail records and must be counted.
            ReviewRecord(
                "hotel-a", "meituan", "m-3", None, 5, False,
                "2026-08-03T13:00:00+00:00", "2026-08-02T12:00:00+00:00",
            ),
            # The same physical-looking ID on another platform is a separate scoped review.
            ReviewRecord(
                "hotel-a", "dianping", "m-3", "大众点评待回复", 2, False,
                "2026-08-03T14:00:00+00:00", "2026-08-02T13:00:00+00:00",
            ),
            # Reviews outside the 60-day detail window must not enter the current queue.
            ReviewRecord(
                "hotel-a", "meituan", "m-old", "历史遗留未回复", 1, False,
                "2026-08-03T15:00:00+00:00", "2026-05-01T13:00:00+00:00",
            ),
            # Another hotel must never enter the current hotel's count.
            ReviewRecord(
                "hotel-b", "meituan", "m-4", "跨酒店数据", 1, False,
                "2026-08-03T15:00:00+00:00", "2026-08-02T14:00:00+00:00",
            ),
        ]

    @staticmethod
    def _expected_22_records() -> list[ReviewRecord]:
        rows: list[ReviewRecord] = []
        for index in range(19):
            rows.append(
                ReviewRecord(
                    "puyue",
                    "meituan",
                    f"mt-{index + 1}",
                    None if index == 0 else f"美团评论{index + 1}",
                    5 if index == 0 else 4,
                    False,
                    f"2026-08-03T{index % 10 + 1:02d}:00:00+00:00",
                    f"2026-08-02T{index % 10 + 1:02d}:00:00+00:00",
                )
            )
        for index in range(3):
            rows.append(
                ReviewRecord(
                    "puyue",
                    "dianping",
                    f"dp-{index + 1}",
                    f"大众点评评论{index + 1}",
                    4,
                    False,
                    f"2026-08-03T{index + 11:02d}:00:00+00:00",
                    f"2026-08-02T{index + 11:02d}:00:00+00:00",
                )
            )
        rows.extend(
            [
                ReviewRecord(
                    "puyue", "meituan", "already-replied", "已回复", 5, True,
                    "2026-08-03T15:00:00+00:00", "2026-08-02T15:00:00+00:00",
                ),
                ReviewRecord(
                    "puyue", "meituan", "outside-window", "超过60日", 2, False,
                    "2026-08-03T15:30:00+00:00", "2026-05-01T15:00:00+00:00",
                ),
                ReviewRecord(
                    "other-hotel", "dianping", "cross-hotel", "其他酒店", 1, False,
                    "2026-08-03T15:40:00+00:00", "2026-08-02T15:40:00+00:00",
                ),
            ]
        )
        return rows

    def test_latest_snapshot_pure_rating_and_60_day_window_define_count(self) -> None:
        repository = MemoryReviewSourceRepository(self._records())
        rows = repository.list_unreplied(hotel_id="hotel-a", as_of=NOW, limit=50)

        self.assertEqual(len(rows), 3)
        self.assertEqual(
            {(row.platform, row.review_id) for row in rows},
            {
                ("meituan", "m-2"),
                ("meituan", "m-3"),
                ("dianping", "m-3"),
            },
        )
        self.assertTrue(any(row.review_content is None for row in rows))
        self.assertNotIn("m-old", {row.review_id for row in rows})

    def test_latest_pending_uses_review_time_not_queue_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = S13Service(
                control_repository=S13ControlRepository(str(root / "control.sqlite")),
                source_repository=MemoryReviewSourceRepository(self._records()),
                task_outbox=SQLiteReviewTaskOutbox(str(root / "task.sqlite")),
            )
            result = service.latest_pending(RequestContext("hotel-a", "owner", "owner-1", NOW))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["platform"], "dianping")

    def test_pending_list_is_capped_at_20_after_exact_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = S13Service(
                control_repository=S13ControlRepository(str(root / "control.sqlite")),
                source_repository=MemoryReviewSourceRepository(self._expected_22_records()),
                task_outbox=SQLiteReviewTaskOutbox(str(root / "task.sqlite")),
            )
            result = service.list_pending(RequestContext("puyue", "owner", "owner-1", NOW))

        counts = Counter(item["platform"] for item in result["items"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 20)
        self.assertEqual(counts, Counter({"meituan": 19, "dianping": 1}))
        self.assertTrue(result["more_may_exist"])
        self.assertIn("待回复评论｜按风险与低分优先展示 20 条", _render(result))

    def test_platform_mapping_prefers_review_platform_semantics(self) -> None:
        self.assertEqual(normalize_platform("美团", default="meituan"), "meituan")
        self.assertEqual(normalize_platform("美团评价", default="meituan"), "meituan")
        self.assertEqual(normalize_platform("大众点评", default="meituan"), "dianping")
        self.assertEqual(normalize_platform("大众点评评价", default="meituan"), "dianping")

    def test_mysql_query_deduplicates_by_review_platform_before_filter_and_limit(self) -> None:
        captured: dict[str, Any] = {}
        table = "meituan_ota_review_detail"
        columns = {
            "hotel_id": "hotel_id",
            "review_id": "review_id",
            "review_content": "review_content",
            "star_rating": "review_score",
            "is_replied": "is_replied",
            "source_snapshot": "snapshot_time",
            "review_time": "review_time",
            "platform_scope": "review_platform",
        }

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql: str, params: tuple[Any, ...]) -> None:
                captured["sql"] = sql
                captured["params"] = params

            def fetchall(self) -> list[dict[str, Any]]:
                return []

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self) -> Cursor:
                return Cursor()

        repository = object.__new__(MySQLReviewSourceRepository)
        repository._columns_cache = {table: columns}
        repository._connect = lambda: Connection()  # type: ignore[method-assign]

        repository._query_table(
            table=table,
            hotel_id="puyue",
            as_of=NOW,
            review_id=None,
            limit=None,
            default_platform="meituan",
        )

        sql = captured["sql"]
        self.assertIn("ROW_NUMBER() OVER", sql)
        self.assertIn("PARTITION BY `review_platform`, `review_id`", sql)
        self.assertIn("`review_time`>=%s", sql)
        self.assertIn("`review_time`<=%s", sql)
        self.assertIn("WHERE `_s13_rn`=1", sql)
        self.assertNotIn("LIMIT %s", sql)
        self.assertEqual(len(captured["params"]), 4)


if __name__ == "__main__":
    unittest.main()
