from __future__ import annotations

import unittest

from runtime.s15_baseline_detail_patch import _append_details


class S15BaselineDetailPatchTests(unittest.TestCase):
    def test_room_hourly_progress_is_inserted_before_market_section(self) -> None:
        base = "一、全店\n\n二、房型\n\n三、大盘订单基准线（估算）\n- 后续长内容"
        payload = {
            "status": "ok",
            "as_of_datetime": "2026-08-06 16:20:00",
            "room_types": {
                "r1": {
                    "room_type_name": "豪华大床房",
                    "hourly_points": [
                        {
                            "hour": 16,
                            "capacity": {"median": 0.5, "sample_count": 6},
                            "target_completion": {"median": 0.6, "sample_count": 6},
                            "exact_sample_count": 6,
                        }
                    ],
                }
            },
        }
        text = _append_details(base, payload)
        room_index = text.index("全部房型小时销售进度")
        market_index = text.index("三、大盘订单基准线")
        self.assertLess(room_index, market_index)
        self.assertIn("豪华大床房", text)
        self.assertIn("16 容50%/完60%/样6", text)
        self.assertNotIn("全店分时销售基准检查点", text)


if __name__ == "__main__":
    unittest.main()
