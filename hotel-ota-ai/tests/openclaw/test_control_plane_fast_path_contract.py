from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestControlPlaneFastPathContract(unittest.TestCase):
    def test_bootstrap_routes_control_plane_writes_before_skill_first(self) -> None:
        text = (ROOT / "BOOTSTRAP.md").read_text(encoding="utf-8")

        fast_path = text.index("## 控制面 Fast Path（先于 Skill-first）")
        skill_first = text.index("## 普通飞书业务读取顺序")
        self.assertLess(fast_path, skill_first)
        self.assertIn("不读取 `router/skill_route_index.md`", text)
        self.assertIn("不加载 `skills/hotel-ota/s01-control-config/SKILL.md`", text)
        self.assertIn("不搜索其他 Skill 或 Scenario", text)
        self.assertIn("feishu-route --production-feishu", text)
        self.assertIn("确认 ROLE-*", text)
        self.assertIn("取消 ROLE-*", text)

    def test_skill_index_excludes_control_plane_writes_from_s1(self) -> None:
        text = (ROOT / "router" / "skill_route_index.md").read_text(encoding="utf-8")

        self.assertIn("ROLE / BIND / CFG 控制面写操作及其确认/取消不属于普通 Skill 路由", text)
        self.assertIn("不得先路由到 S1 再找工具", text)
        self.assertIn("不包含 ROLE/BIND/CFG 控制面写操作及确认/取消", text)
        self.assertIn("`把张三换成前台`", text)
        self.assertIn("`我的权限是什么`", text)

    def test_s1_owner_role_rule_matches_runtime_contract(self) -> None:
        text = (
            ROOT
            / "skills"
            / "hotel-ota"
            / "s01-control-config"
            / "references"
            / "rules.md"
        ).read_text(encoding="utf-8")

        self.assertNotIn("但不可管理角色表", text)
        self.assertIn("管理其他 `owner/operator/frontdesk`", text)
        self.assertIn("不得修改自己", text)
        self.assertIn("不得修改 `admin`", text)
        self.assertIn("owner 发起的 ROLE 请求可由该 owner 自己确认", text)


if __name__ == "__main__":
    unittest.main()
