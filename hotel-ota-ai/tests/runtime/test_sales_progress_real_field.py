from __future__ import annotations

import datetime as dt
import unittest

from runtime.sales_progress.core import (
    calculate_room_fact,
    classify_delta,
    combined_diagnosis,
    select_complete_batch,
    weighted_quantile,
)
from runtime.sales_progress.service import build_baseline, build_deviation


class FakeRepository:
    def __init__(self) -> None:
        self.target = dt.date(2026, 8, 8)
        self.history_days = [self.target - dt.timedelta(days=7 * i) for i in range(1, 7)]

    def hourly_history(self, hotel_id, start_date, end_date, as_of):
        rows = []
        for day_index, day in enumerate(self.history_days):
            final_a = 10 + day_index
            final_b = 8 + day_index
            for hour in range(24):
                ratio = hour / 23 if hour else 0
                for room_id, total, final in (("A", 20, final_a), ("B", 15, final_b)):
                    committed = round(final * ratio)
                    rows.append(
                        {
                            "hotel_id": hotel_id,
                            "stay_date": day.isoformat(),
                            "snapshot_hour": f"{day.isoformat()} {hour:02d}:00:00",
                            "snapshot_time": f"{day.isoformat()} {hour:02d}:05:00",
                            "room_type_id": room_id,
                            "room_type_name": room_id,
                            "pms_room_type_id": f"pms-{room_id}",
                            "total_rooms": total,
                            "available_rooms": total - committed,
                            "occupied_rooms": committed,
                            "overbooking_rooms": 0,
                        }
                    )
        return rows

    def room_daily(self, hotel_id, start_date, end_date, as_of):
        rows = []
        for day_index, day in enumerate(self.history_days):
            rows.extend(
                [
                    {
                        "hotel_id": hotel_id,
                        "business_date": day.isoformat(),
                        "room_type_id": "A",
                        "room_nights": 10 + day_index,
                        "room_revenue": 1000 + day_index * 100,
                        "snapshot_time": f"{day} 23:59:00",
                    },
                    {
                        "hotel_id": hotel_id,
                        "business_date": day.isoformat(),
                        "room_type_id": "B",
                        "room_nights": 8 + day_index,
                        "room_revenue": 720 + day_index * 90,
                        "snapshot_time": f"{day} 23:59:00",
                    },
                ]
            )
        return rows

    def hotel_daily_total(self, hotel_id, start_date, end_date, as_of):
        return [
            {
                "hotel_id": hotel_id,
                "source_platform": "pms",
                "business_date": day.isoformat(),
                "dimension_type": "总营业指标",
                "dimension_name": "总营业指标",
                "room_nights": 18 + day_index * 2,
                "room_revenue": 1720 + day_index * 190,
                "snapshot_time": f"{day} 23:59:00",
            }
            for day_index, day in enumerate(self.history_days)
        ]

    def room_revenue(self, hotel_id, start_date, end_date, as_of):
        return [
            {
                "business_date": day.isoformat(),
                "room_type_id": room_id,
                "room_daily_price": price,
                "room_nights": nights,
                "room_fee": price * nights,
                "snapshot_time": f"{day} 23:59:00",
            }
            for day in self.history_days
            for room_id, price, nights in (("A", 100, 10), ("A", 120, 5), ("B", 90, 8))
        ]

    def ota_business_metrics(self, platform, hotel_id, start_date, end_date, as_of):
        rows = []
        for day in self.history_days:
            metrics = (
                [
                    ("FLOW_EXPOSURE_UV", 1000, "人"),
                    ("FLOW_INTENTION_UV", 100, "人"),
                    ("FLOW_PAY_ORDER_CNT", 10, "单"),
                ]
                if platform == "meituan"
                else [
                    ("list_page_exposure_count", 2000, "count"),
                    ("detail_page_visitor_count", 200, "person"),
                    ("order_submit_count", 20, "order"),
                ]
            )
            for code, value, unit in metrics:
                rows.append(
                    {
                        "business_date": day.isoformat(),
                        "metric_code": code,
                        "metric_value": value,
                        "metric_unit": unit,
                    }
                )
        return rows

    def flow_30d(self, platform, hotel_id, as_of):
        return [
            {
                "hotel_id": hotel_id,
                "period_start_date": "2026-07-01",
                "period_end_date": "2026-07-30",
                "snapshot_time": "2026-07-30 12:00:00",
            }
        ]

    def current_forecast(self, hotel_id, stay_date, as_of):
        return [
            {
                "hotel_id": hotel_id,
                "stay_date": stay_date,
                "snapshot_time": f"{stay_date} 16:00:00",
                "room_type_id": "A",
                "room_type_name": "A",
                "pms_room_type_id": "pms-A",
                "total_rooms": 20,
                "available_rooms": 12,
                "occupied_rooms": 5,
                "overbooking_rooms": 1,
            },
            {
                "hotel_id": hotel_id,
                "stay_date": stay_date,
                "snapshot_time": f"{stay_date} 16:00:00",
                "room_type_id": "B",
                "room_type_name": "B",
                "pms_room_type_id": "pms-B",
                "total_rooms": 15,
                "available_rooms": 10,
                "occupied_rooms": 4,
                "overbooking_rooms": 0,
            },
        ]


class SalesProgressCoreTests(unittest.TestCase):
    def test_committed_uses_inventory_and_overbooking_not_occupied(self):
        result = calculate_room_fact(
            {
                "room_type_id": "A",
                "total_rooms": 20,
                "available_rooms": 12,
                "occupied_rooms": 2,
                "overbooking_rooms": 1,
            }
        )
        self.assertEqual(result["base_committed_sold"], 8)
        self.assertEqual(result["committed_sold"], 9)
        self.assertNotEqual(result["committed_sold"], result["occupied_rooms"])

    def test_batch_selection_never_stitches_room_latest_rows(self):
        rows = [
            {
                "snapshot_time": "2026-08-08 15:00:00",
                "snapshot_hour": "2026-08-08 15:00:00",
                "room_type_id": "A",
                "total_rooms": 10,
                "available_rooms": 5,
                "overbooking_rooms": 0,
            },
            {
                "snapshot_time": "2026-08-08 15:00:00",
                "snapshot_hour": "2026-08-08 15:00:00",
                "room_type_id": "B",
                "total_rooms": 10,
                "available_rooms": 6,
                "overbooking_rooms": 0,
            },
            {
                "snapshot_time": "2026-08-08 16:00:00",
                "snapshot_hour": "2026-08-08 16:00:00",
                "room_type_id": "A",
                "total_rooms": 10,
                "available_rooms": 4,
                "overbooking_rooms": 0,
            },
        ]
        selected = select_complete_batch(rows, expected_room_types=["A", "B"], requested_hour=16)
        self.assertEqual(selected.observed_hour, 15)
        self.assertEqual({row["room_type_id"] for row in selected.rows}, {"A", "B"})

    def test_threshold_boundaries(self):
        self.assertEqual(classify_delta(-25), "severe_slow")
        self.assertEqual(classify_delta(-15), "significant_slow")
        self.assertEqual(classify_delta(-8), "normal")
        self.assertEqual(classify_delta(8), "fast")
        self.assertEqual(classify_delta(15), "significant_fast")

    def test_dual_line_diagnosis(self):
        self.assertEqual(
            combined_diagnosis("significant_slow", "fast"), "ambitious_target_gap"
        )
        self.assertEqual(
            combined_diagnosis("normal", "slow"), "conservative_target_on_track"
        )

    def test_weighted_quantile_uses_room_nights(self):
        self.assertEqual(weighted_quantile([(100, 9), (200, 1)], 0.5), 100)


class SalesProgressServiceTests(unittest.TestCase):
    def test_s15_builds_hotel_room_price_and_ota_families(self):
        repo = FakeRepository()
        result = build_baseline(
            repo,
            hotel_id="hotel-a",
            target_date=repo.target.isoformat(),
            as_of_datetime=f"{repo.target} 23:59:59",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["selected_tier"], "P4_same_weekday")
        self.assertEqual(set(result["room_types"]), {"A", "B"})
        self.assertEqual(len(result["hotel"]["hourly_points"]), 24)
        self.assertAlmostEqual(
            result["room_types"]["A"]["price_baseline"]["weighted_avg"],
            106.66666666666667,
        )
        self.assertAlmostEqual(
            result["ota_baselines"]["meituan"]["baselines"]["first_conversion"][
                "median"
            ],
            0.1,
        )
        self.assertAlmostEqual(
            result["ota_baselines"]["ctrip"]["baselines"]["detail_to_submit_ratio"][
                "median"
            ],
            0.1,
        )
        self.assertEqual(result["rolling_30d_context"]["status"], "single_window_reference")
        self.assertIn("market_orders_baseline", result["unavailable_baseline_families"])

    def test_s16_uses_current_forecast_and_builds_room_structure(self):
        repo = FakeRepository()
        baseline = build_baseline(
            repo,
            hotel_id="hotel-a",
            target_date=repo.target.isoformat(),
            as_of_datetime=f"{repo.target} 23:59:59",
        )
        result = build_deviation(
            repo,
            hotel_id="hotel-a",
            target_date=repo.target.isoformat(),
            as_of_datetime=f"{repo.target} 16:30:00",
            baseline=baseline,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["hotel_result"]["committed_sold"], 14)
        self.assertEqual(len(result["room_type_results"]), 2)
        self.assertIn("slow_room_type_count", result["structure_summary"])

    def test_future_stay_date_does_not_compare_same_day_curve(self):
        repo = FakeRepository()
        baseline = build_baseline(
            repo,
            hotel_id="hotel-a",
            target_date=repo.target.isoformat(),
            as_of_datetime=f"{repo.target} 23:59:59",
        )
        result = build_deviation(
            repo,
            hotel_id="hotel-a",
            target_date=repo.target.isoformat(),
            as_of_datetime="2026-08-07 16:00:00",
            baseline=baseline,
        )
        self.assertEqual(result["status"], "not_applicable")
        self.assertEqual(result["reason"], "future_stay_date_requires_lead_time_baseline")


if __name__ == "__main__":
    unittest.main()
