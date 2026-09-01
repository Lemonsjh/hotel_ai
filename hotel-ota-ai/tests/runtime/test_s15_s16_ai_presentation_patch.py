from __future__ import annotations

import unittest

from runtime.s15_s16_ai_presentation_patch import _replace_structure_section


class S15S16AiPresentationPatchTests(unittest.TestCase):
    def test_structure_section_separates_capacity_and_target_counts(self) -> None:
        source = "\n".join(
            [
                "S16 销售进度",
                "三、房型结构",
                "- 滞后房型 0 个；超前房型 0 个。",
                "- 结构判断：未发现异常。",
                "数据时效：20分钟。",
                "本结果只说明销售节奏。",
            ]
        )
        report = {
            "room_type_results": [{"room_type_id": "a"}, {"room_type_id": "b"}],
            "structure_summary": {
                "room_type_count": 2,
                "capacity_line_available_count": 2,
                "capacity_slow_room_type_count": 1,
                "capacity_fast_room_type_count": 1,
                "target_line_available_count": 0,
                "target_slow_room_type_count": 0,
                "target_fast_room_type_count": 0,
                "labels": [],
            },
        }
        rendered = _replace_structure_section(source, report)
        self.assertIn("容量线：可判断 2/2 个房型；滞后 1 个，超前 1 个", rendered)
        self.assertIn("参考完成线：可判断 0/2 个房型", rendered)
        self.assertIn("其余 2 个房型缺少可用的历史最终已售分母", rendered)
        self.assertNotIn("滞后房型 0 个；超前房型 0 个", rendered)
        self.assertIn("数据时效：20分钟", rendered)


if __name__ == "__main__":
    unittest.main()
