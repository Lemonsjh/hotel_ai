from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "runtime" / "sales_progress" / "presentation.py"
spec = importlib.util.spec_from_file_location("sales_progress_presentation_test_module", PATH)
presentation = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(presentation)


class SalesProgressPresentationTests(unittest.TestCase):
    @staticmethod
    def _points() -> list[dict]:
        return [
            {
                "hour": hour,
                "capacity": {
                    "median": 0.4,
                    "p25": 0.3,
                    "p80": 0.5,
                    "sample_count": 8 if hour >= 9 else 0,
                },
                "target_completion": {
                    "median": 0.5,
                    "p25": 0.4,
                    "p80": 0.6,
                    "sample_count": 8 if hour >= 9 else 0,
                },
                "maturity": "stable" if hour >= 9 else "trend_only",
            }
            for hour in range(24)
        ]

    def test_s15_business_output_contains_full_families_and_no_fake_orders(self) -> None:
        points = self._points()
        payload = {
            "status": "ok",
            "target_date": "2026-08-03",
            "as_of_datetime": "2026-08-03 16:47:00",
            "active_target_source": "historical_inferred_target",
            "selected_tier": "P4_same_weekday",
            "selected_dates": [f"2026-07-{day:02d}" for day in range(1, 9)],
            "hotel": {
                "effective_target_room_nights": 28,
                "historical_revenue_target": {"median": 6000},
                "hourly_points": points,
            },
            "room_types": {
                "R1": {
                    "room_type_id": "R1",
                    "room_type_name": "大床房",
                    "effective_target_room_nights": 10,
                    "hourly_points": points,
                    "price_baseline": {"median": 220},
                }
            },
            "ota_baselines": {
                "meituan": {"baselines": {}},
                "ctrip": {"baselines": {}},
            },
            "unavailable_baseline_families": {
                "market_orders_baseline": "source_semantic_unavailable"
            },
        }
        result = presentation.attach_s15_user_view(payload)
        text = result["user_message"]
        self.assertIn("全店两条销售节奏基准", text)
        self.assertIn("容量节奏", text)
        self.assertIn("参考完成节奏", text)
        self.assertIn("房型基准", text)
        self.assertIn("平台流量与转化基准", text)
        self.assertIn("历史同类日参考最终已售房量", text)
        self.assertIn("大床房", text)
        self.assertNotIn("目标订单", text)
        self.assertNotIn("historical_inferred_target", text)
        self.assertFalse(result["order_count_available"])

    def test_s16_business_output_contains_hotel_room_dual_lines(self) -> None:
        line = {
            "actual_progress": 0.8,
            "baseline_median": 0.5,
            "baseline_p25": 0.4,
            "baseline_p80": 0.6,
            "delta_pp": 30,
            "expected_sold": 14,
            "room_gap": 9,
            "remaining_target_gap": 5,
            "status": "significant_fast",
        }
        report = {
            "status": "ok",
            "target_date": "2026-08-03",
            "as_of_datetime": "2026-08-03 16:47:00",
            "checkpoint_gap_minutes": 8,
            "target_source": "historical_inferred_target",
            "hotel_result": {
                "committed_sold": 23,
                "total_rooms": 31,
                "effective_target_room_nights": 28,
                "capacity_line": line,
                "target_line": line,
                "combined_diagnosis": "on_track_or_ahead",
            },
            "room_type_results": [
                {
                    "room_type_id": "R1",
                    "room_type_name": "大床房",
                    "committed_sold": 5,
                    "total_rooms": 8,
                    "capacity_line": line,
                    "target_line": line,
                    "maturity": "stable",
                }
            ],
            "structure_summary": {
                "slow_room_type_count": 0,
                "fast_room_type_count": 1,
                "slow_target_share": 0,
                "labels": [],
            },
        }
        result = presentation.attach_s16_user_view(report)
        text = result["user_message"]
        self.assertIn("全店双线判断", text)
        self.assertIn("容量销售节奏", text)
        self.assertIn("房型双线", text)
        self.assertIn("承诺已售房量", text)
        self.assertIn("不等同于物理在住房", text)
        self.assertIn("不据此直接推断必然满房", text)
        self.assertNotIn("on_track_or_ahead", text)
        self.assertNotIn("target_room_nights", text)
        self.assertNotIn("1 单", text)


if __name__ == "__main__":
    unittest.main()
