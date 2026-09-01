from __future__ import annotations

from datetime import datetime
import unittest

from runtime import historical_report_scope_patch as patch
from runtime import s14_bundle_builder, time_context
from runtime import feishu_command_router as router
from runtime import s16_meituan_projection_advisory_patch as s16_patch


class HistoricalReportDateScopeTests(unittest.TestCase):
    def test_yesterday_operation_report_routes_to_s14(self) -> None:
        message = "生成昨天经营日报"

        self.assertTrue(
            patch.is_historical_operation_report(
                message,
                now=datetime(2026, 8, 5, 14, 26),
            )
        )
        self.assertEqual(router._detect_intent(message), "operation_diagnosis")
        self.assertTrue(s14_bundle_builder.is_s14_operation_message(message))

    def test_historical_daily_report_uses_business_day_close(self) -> None:
        context = time_context.resolve_request_as_of_time(
            "生成昨天经营日报",
            now=datetime(2026, 8, 5, 14, 26),
        )

        self.assertEqual(context["target_business_date"], "2026-08-04")
        self.assertEqual(context["as_of_time"], "2026-08-04 23:59:59")
        self.assertEqual(
            context["as_of_time_source"],
            "historical_report_day_close",
        )

    def test_explicit_historical_report_cutoff_is_preserved(self) -> None:
        context = time_context.resolve_request_as_of_time(
            "生成昨天12点经营日报",
            now=datetime(2026, 8, 5, 14, 26),
        )

        self.assertEqual(context["target_business_date"], "2026-08-04")
        self.assertEqual(context["as_of_time"], "2026-08-04 12:00:00")
        self.assertEqual(context["as_of_time_source"], "message_explicit")

    def test_s14_parser_accepts_space_separated_full_datetime(self) -> None:
        parsed = patch.parse_s14_request_as_of(
            "2026-08-04 23:59:59",
            now=datetime(2026, 8, 5, 14, 26),
        )

        self.assertEqual(
            parsed.isoformat(timespec="seconds"),
            "2026-08-04T23:59:59+08:00",
        )

    def test_meituan_proxy_fails_closed_on_cross_business_date(self) -> None:
        class Repository:
            def _query(self, *_args, **_kwargs):  # pragma: no cover
                raise AssertionError("cross-date proxy must not query")

        result = s16_patch.build_meituan_market_proxy(
            Repository(),
            hotel_id="hotel-puyue",
            target_date="2026-08-04",
            as_of_datetime="2026-08-05 14:26:00",
            baseline_market_orders=276.9,
            baseline_market_share=0.096,
        )

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(
            result["reason"],
            "target_as_of_business_date_mismatch",
        )
        self.assertFalse(result["cross_business_date_fallback_allowed"])

    def test_historical_s16_message_never_labels_proxy_as_today(self) -> None:
        def previous(_report):  # type: ignore[no-untyped-def]
            return (
                "- 美团大盘（估算）：当前约 253单；"
                "本店今日美团订单代理 6单，同行平均 13单/店。"
            )

        renderer = patch._wrap_s16_message(previous)
        text = renderer(
            {
                "target_date": "2026-08-04",
                "dynamic_diagnosis": {
                    "target_date": "2026-08-04",
                    "meituan_market_proxy": {
                        "status": "available",
                        "target_business_date": "2026-08-04",
                    },
                },
            }
        )

        self.assertNotIn("本店今日美团订单代理", text)
        self.assertIn("本店当日美团订单代理 6单", text)


if __name__ == "__main__":
    unittest.main()
