from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from runtime.algorithms.time_aware_progress import resolve_progress_at_time
from runtime.business_context_resolver import resolve_business_context
from runtime.demo_today_generator import generate_today_demo_result


class TestTimeAwareProgress(unittest.TestCase):
    def test_resolves_progress_at_same_time_without_future_leak(self) -> None:
        snapshots = [
            {"snapshot_at": "2026-06-15 16:40:00", "sold_rooms": 16, "orders_cumulative": 10, "occupancy_rate": 0.32},
            {"snapshot_at": "2026-06-15 18:20:00", "sold_rooms": 24, "orders_cumulative": 15, "occupancy_rate": 0.48},
            {"snapshot_at": "2026-06-15 22:00:00", "sold_rooms": 34, "orders_cumulative": 21, "occupancy_rate": 0.68},
        ]
        curve = [
            {"hour": "16:40", "target_sold_rooms": 15},
            {"hour": "18:20", "target_sold_rooms": 25},
            {"hour": "22:00", "target_sold_rooms": 34},
        ]

        at_1640 = resolve_progress_at_time(snapshots, curve, "16:40", daily_target_room_nights=36)
        at_1820 = resolve_progress_at_time(snapshots, curve, "18:20", daily_target_room_nights=36)
        at_2200 = resolve_progress_at_time(snapshots, curve, "22:00", daily_target_room_nights=36)

        self.assertEqual(at_1640["as_of_actual_sold_rooms"], 16)
        self.assertEqual(at_1640["as_of_target_sold_rooms"], 15)
        self.assertEqual(at_1640["as_of_checkpoint_gap"], 1)
        self.assertEqual(at_1640["daily_remaining_gap"], 20)
        self.assertNotEqual(at_1640["as_of_actual_sold_rooms"], 34)
        self.assertEqual(at_1820["as_of_actual_sold_rooms"], 24)
        self.assertEqual(at_1820["as_of_target_sold_rooms"], 25)
        self.assertEqual(at_1820["as_of_checkpoint_gap"], -1)
        self.assertNotEqual(at_1820["as_of_actual_sold_rooms"], 34)
        self.assertEqual(at_2200["as_of_actual_sold_rooms"], 34)
        self.assertEqual(at_2200["as_of_target_sold_rooms"], 34)
        self.assertEqual(at_2200["as_of_checkpoint_gap"], 0)

    def test_blocks_future_only_data_for_past_checkpoint(self) -> None:
        result = resolve_progress_at_time(
            [{"snapshot_at": "2026-06-15 22:00:00", "sold_rooms": 34}],
            [{"hour": "16:40", "target_sold_rooms": 15}],
            "16:40",
            daily_target_room_nights=36,
        )

        self.assertEqual(result["status"], "future_data_leak_blocked")
        self.assertIsNone(result["as_of_actual_sold_rooms"])
        self.assertIn("future_snapshot_after_as_of_time", result["missing_fields"])

    def test_business_context_resolver_uses_generated_sqlite_and_active_target(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "synthetic.sqlite")
            generate_today_demo_result(
                argparse.Namespace(
                    business_date="2026-06-15",
                    seed=20260615,
                    profile="normal",
                    hotel_id="puyue-demo",
                    write_db=True,
                    write_fixtures=False,
                    dry_run=False,
                    output_dir=None,
                    db=db_path,
                )
            )
            context = resolve_business_context(
                db_path=db_path,
                hotel_id="puyue-demo",
                business_date="2026-06-15",
                as_of_time="16:00",
                mode="demo",
            )

        self.assertEqual(context["status"], "ok")
        self.assertEqual(context["context_source"], "sqlite_synthetic_today_demo")
        self.assertEqual(context["data_source_type"], "synthetic_today_demo")
        self.assertEqual(context["freshness_status"], "synthetic_current_day")
        self.assertEqual(context["active_target_source"], "synthetic_today_demo")
        self.assertEqual(context["time_grain"], "as_of_time")
        self.assertIn("as_of_checkpoint_gap", context["progress"])
        self.assertEqual(
            context["progress"]["daily_target_room_nights"],
            context["daily_target_room_nights"],
        )


if __name__ == "__main__":
    unittest.main()
