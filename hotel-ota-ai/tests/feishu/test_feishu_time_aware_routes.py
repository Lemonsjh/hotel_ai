from __future__ import annotations

import unittest
from datetime import datetime

from runtime.feishu_command_router import route_feishu_command
from runtime.time_context import resolve_request_as_of_time


class TestFeishuTimeAwareRoutes(unittest.TestCase):
    def test_realtime_message_defaults_to_request_clock_business_date(self) -> None:
        context = resolve_request_as_of_time("实时出租率", now=datetime(2026, 7, 5, 15, 25, 0))

        self.assertEqual(context["target_business_date"], "2026-07-05")
        self.assertEqual(context["as_of_time"], "2026-07-05 15:25:00")
        self.assertEqual(context["as_of_time_source"], "request_clock")

    def test_yesterday_message_resolves_business_date_and_full_as_of_time(self) -> None:
        context = resolve_request_as_of_time("昨天14点实时出租率", now=datetime(2026, 7, 5, 15, 25, 0))

        self.assertEqual(context["target_business_date"], "2026-07-04")
        self.assertEqual(context["as_of_time"], "2026-07-04 14:00:00")
        self.assertEqual(context["as_of_time_source"], "message_explicit")

    def test_progress_message_passes_explicit_as_of_time_to_runtime(self) -> None:
        result = route_feishu_command("16:40 \u8fdb\u5ea6\u8bca\u65ad", role="owner", render=True)

        self.assertEqual(result["intent"], "progress_deviation_demo")
        self.assertEqual(result["as_of_time"][-5:], "16:40")
        self.assertEqual(result["as_of_time_source"], "message_explicit")
        self.assertNotIn("22:00", result["send_payload"]["text"])

    def test_revenue_message_uses_explicit_time_aware_context(self) -> None:
        result = route_feishu_command("18:20 \u6536\u76ca\u51b3\u7b56", role="owner", render=True)

        self.assertEqual(result["intent"], "revenue_decision")
        self.assertEqual(result["as_of_time"][-8:], "18:20:00")
        self.assertEqual(result["as_of_time_source"], "message_explicit")
        self.assertNotIn("progress_trend_status", result)

    def test_normal_business_payload_hides_algorithm_detail_and_hourly_tables(self) -> None:
        revenue = route_feishu_command("18:20 \u6536\u76ca\u51b3\u7b56", role="owner", render=True)
        progress = route_feishu_command("16:40 \u8fdb\u5ea6\u8bca\u65ad", role="owner", render=True)

        for field in [
            "contract_input_coverage",
            "runtime_feed_coverage",
            "algorithm_usage_coverage",
            "algorithm_used_inputs",
            "runtime_command",
            "model",
            "provider",
        ]:
            self.assertNotIn(field, revenue["send_payload"]["text"])
        for field in ["actual_hourly_sales", "target_hourly_curve", "actual_vs_target_hourly", "runtime_command"]:
            self.assertNotIn(field, progress["send_payload"]["text"])
        self.assertLessEqual(len(revenue["send_payload"]["text"]), 1200)
        self.assertLessEqual(len(progress["send_payload"]["text"]), 1200)


if __name__ == "__main__":
    unittest.main()
