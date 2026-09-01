from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class S15S16ContractFixTests(unittest.TestCase):
    def test_current_as_of_never_defaults_to_end_of_day(self) -> None:
        baseline = (ROOT / "runtime" / "decisions" / "baseline.py").read_text(
            encoding="utf-8"
        )
        deviation = (ROOT / "runtime" / "decisions" / "deviation.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("23:59:59", baseline)
        self.assertNotIn("23:59:59", deviation)
        self.assertIn("now_local()", baseline)
        self.assertIn("return now_local()", deviation)

    def test_order_count_is_not_derived_from_sold_rooms_or_room_nights(self) -> None:
        baseline = (ROOT / "runtime" / "decisions" / "baseline.py").read_text(
            encoding="utf-8"
        )
        deviation = (ROOT / "runtime" / "decisions" / "deviation.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"target_orders": None', baseline)
        self.assertIn('"actual_orders": None', deviation)
        self.assertIn("orders_not_derivable_from_room_nights", baseline)
        self.assertIn("orders_not_derivable_from_room_nights", deviation)

    def test_s16_no_longer_consumes_s2_capability_result(self) -> None:
        orchestrator = (ROOT / "runtime" / "skill_orchestrator.py").read_text(
            encoding="utf-8"
        )
        dependency_contract = (ROOT / "config" / "skill-dependencies.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '"S16_PROGRESS_DEVIATION": ["S15_SALES_BASELINE"]', orchestrator
        )
        s16_section = dependency_contract.split("S5_REVENUE_DECISION:", 1)[0]
        self.assertIn("- S15_SALES_BASELINE", s16_section)
        self.assertNotIn("S2_OPERATING_SNAPSHOT", s16_section)

    def test_runtime_installs_s15_s16_output_patch(self) -> None:
        runtime_init = (ROOT / "runtime" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("_install_s15_s16_runtime_patch()", runtime_init)

    def test_s15_uses_short_cache_but_supports_forced_rebuild(self) -> None:
        baseline = (ROOT / "runtime" / "decisions" / "baseline.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("HOTEL_OTA_S15_CACHE_TTL_SECONDS", baseline)
        self.assertIn('parser.add_argument("--force-rebuild"', baseline)
        self.assertIn("explicit_as_of or force_rebuild", baseline)


if __name__ == "__main__":
    unittest.main()
