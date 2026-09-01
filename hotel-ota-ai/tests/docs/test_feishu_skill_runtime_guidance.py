from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestFeishuSkillRuntimeGuidance(unittest.TestCase):
    def test_s02_realtime_occupancy_guidance_does_not_route_to_snapshot(self) -> None:
        skill_text = (ROOT / "skills/hotel-ota/s02-operating-snapshot/SKILL.md").read_text(encoding="utf-8")
        commands_text = (ROOT / "skills/hotel-ota/s02-operating-snapshot/references/runtime_commands.md").read_text(
            encoding="utf-8"
        )
        rules_text = (ROOT / "skills/hotel-ota/s02-operating-snapshot/references/rules.md").read_text(
            encoding="utf-8"
        )
        triggers_text = (ROOT / "skills/hotel-ota/s02-operating-snapshot/config/triggers.yaml").read_text(
            encoding="utf-8"
        )
        openclaw_text = (ROOT / "skills/hotel-ota/s02-operating-snapshot/openclaw.skill.yaml").read_text(
            encoding="utf-8"
        )
        combined = "\n".join([skill_text, commands_text, rules_text, triggers_text, openclaw_text])

        self.assertIn("feishu-route --production-feishu", combined)
        self.assertIn("expected-occupancy", combined)
        self.assertIn("jd01", combined)
        self.assertIn("jd04", combined)
        self.assertIn("kf11", combined)
        self.assertIn("target_business_date", combined)
        self.assertIn("DATE(arrival_time)", combined)
        self.assertIn("不是 `jd01.business_date`", combined)
        self.assertNotIn("User says \"实时出租率\": route to `operating_snapshot` and run `snapshot`.", combined)
        self.assertNotIn("runtime_command: python runtime/hotel_ota_runtime.py snapshot --hotel-id <hotel_id>", combined)
        self.assertNotIn("occupancy_rate=sold_rooms/available_rooms", combined)
        self.assertNotIn("最新日结", combined)

    def test_s14_guidance_uses_versioned_capability_results_only(self) -> None:
        root = ROOT / "skills/hotel-ota/s14-operation-diagnosis"
        paths = [
            root / "SKILL.md",
            root / "references/input_schema.json",
            root / "references/output_schema.json",
            root / "references/rules.md",
            root / "references/runtime_commands.md",
            root / "openclaw.skill.yaml",
            root / "config/triggers.yaml",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

        self.assertIn("versioned_capability_results_only", combined)
        self.assertIn("S2/S4/S7/S8/S9/S10/S12/S15/S16/S17", combined)
        self.assertIn("runtime.s14_capability_cli", combined)
        self.assertIn("s14_direct_source_removed_use_versioned_capability_results", combined)
        self.assertIn("direct_business_table_read_allowed", combined)
        self.assertIn("missing_input", combined)
        self.assertNotIn("normalize-sample --sample meituan-price", combined)
        self.assertNotIn("输出 A/B 任务和责任人", combined)
        self.assertNotIn("database-query --db-kind mysql --template operating_snapshot --hotel-id puyue", combined)

    def test_feishu_auth_guard_requires_trusted_context_or_explicit_guard(self) -> None:
        text = (ROOT / "skills/feishu_auth_guard/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("生产 Feishu 业务必须", text)
        self.assertIn("missing_required_feishu_auth_context", text)
        self.assertIn("不得把缺少可信上下文误报为群未绑定", text)
        self.assertNotIn("optional Feishu authorization preflight", text)
        self.assertNotIn("Do not run this guard before every business skill", text)


if __name__ == "__main__":
    unittest.main()
