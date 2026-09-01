from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT / "runtime" / "s15_s16_runtime_patch.py"
spec = importlib.util.spec_from_file_location("s15_s16_patch_test_module", PATCH_PATH)
patch = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(patch)


class S15S16RuntimePatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = dict(sys.modules)
        runtime = types.ModuleType("runtime")
        runtime.__path__ = []
        sys.modules["runtime"] = runtime

        common = types.ModuleType("runtime.common")
        common.DEFAULT_DB = ":memory:"
        sys.modules["runtime.common"] = common

        decisions = types.ModuleType("runtime.decisions")
        decisions.__path__ = []
        sys.modules["runtime.decisions"] = decisions

        baseline_mod = types.ModuleType("runtime.decisions.baseline")

        def baseline(_args):
            return None

        baseline_mod.baseline = baseline
        sys.modules["runtime.decisions.baseline"] = baseline_mod

        deviation_mod = types.ModuleType("runtime.decisions.deviation")

        def deviation(_args):
            return None

        deviation_mod.deviation = deviation
        sys.modules["runtime.decisions.deviation"] = deviation_mod

        sales_progress = types.ModuleType("runtime.sales_progress")
        sales_progress.__path__ = []
        sys.modules["runtime.sales_progress"] = sales_progress

        presentation = types.ModuleType("runtime.sales_progress.presentation")
        presentation.attach_s15_user_view = lambda value: {
            **value,
            "user_message": "完整中文S15",
            "summary": "完整中文S15",
        }
        presentation.attach_s16_user_view = lambda value: {
            **value,
            "user_message": "完整中文S16",
            "summary": "完整中文S16",
        }
        sys.modules["runtime.sales_progress.presentation"] = presentation

        safety_pkg = types.ModuleType("runtime.safety")
        safety_pkg.__path__ = []
        sys.modules["runtime.safety"] = safety_pkg
        safety = types.ModuleType("runtime.safety.feishu_output")
        safety.feishu_output_gate = lambda **_kwargs: {"status": "ok"}
        sys.modules["runtime.safety.feishu_output"] = safety

    def tearDown(self) -> None:
        sys.modules.clear()
        sys.modules.update(self.saved)

    @staticmethod
    def _fake_router_module(intent: str):
        module = types.SimpleNamespace()
        calls: list[str] = []

        def original_route(message, *args, **kwargs):
            calls.append(message)
            if message == "身份":
                return {
                    "status": "ok",
                    "resolved_hotel_id": "hotel-1",
                    "personal_role": "owner",
                    "output_profile": "owner_business",
                }
            return {"status": "old"}

        module.route_feishu_command = original_route
        module._detect_intent = lambda _message: intent
        module._explicit_demo_requested = lambda _message: False
        module.default_output_profile = (
            lambda role, explicit=None: explicit or "owner_business"
        )
        module.resolve_request_as_of_time = (
            lambda _message, explicit_as_of_time=None: {
                "target_business_date": "2026-08-03",
                "as_of_time": explicit_as_of_time,
            }
        )
        module.now_local = lambda: "2026-08-03 16:57:00"
        module._capture_runtime_emit = (
            lambda func, ns: (
                {"status": "ok", "baseline": {"status": "ok"}}
                if func.__name__ == "baseline"
                else {"status": "ok"}
            )
        )
        module._base_result = (
            lambda name, role, output_profile=None: {
                "intent": name,
                "auth_role": role,
                "output_profile": output_profile,
            }
        )
        module.__name__ = "runtime.feishu_command_router"
        return module, calls

    def test_production_s15_executes_business_query_once(self) -> None:
        module, calls = self._fake_router_module("sales_baseline_demo")
        patch._patch_router(module)
        result = module.route_feishu_command(
            "s15", force_feishu_auth=True, render=False, db_path=":memory:"
        )
        self.assertEqual(calls, ["身份"])
        self.assertEqual(result["execution_count"], 1)
        self.assertEqual(result["dependency_runs"], [])
        self.assertEqual(result["user_message"], "完整中文S15")

    def test_explicit_demo_keeps_original_demo_route(self) -> None:
        module, calls = self._fake_router_module("progress_deviation_demo")
        module._explicit_demo_requested = lambda _message: True
        patch._patch_router(module)
        result = module.route_feishu_command(
            "演示 s16", force_feishu_auth=True, render=False
        )
        self.assertEqual(result["status"], "old")
        self.assertEqual(calls, ["演示 s16"])

    def test_direct_delivery_only_exposes_business_message(self) -> None:
        rendered, payload = patch._direct_delivery(
            {
                "intent": "progress_deviation_demo",
                "user_message": "中文业务结果",
                "output_profile": "owner_business",
            },
            "owner",
        )
        self.assertEqual(payload["text"], "中文业务结果")
        self.assertEqual(rendered["visible_fields"], ["user_message"])
        self.assertNotIn("target_room_nights", payload["text"])

    def test_room_names_are_preserved_without_second_query(self) -> None:
        module = types.SimpleNamespace()
        module.__name__ = "runtime.sales_progress.baseline_service"
        module._sales_lines = lambda *_args: ({}, {"R1": {"room_type_id": "R1"}})
        patch._patch_baseline_service(module)
        _, rooms = module._sales_lines(
            [],
            {
                ("2026-08-01", 16): [
                    {"room_type_id": "R1", "room_type_name": "大床房"}
                ]
            },
            [],
            [],
        )
        self.assertEqual(rooms["R1"]["room_type_name"], "大床房")


if __name__ == "__main__":
    unittest.main()
