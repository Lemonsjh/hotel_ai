from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "demo_data"


def load_json(name: str) -> dict:
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


class TestDemoDatasetCompleteness(unittest.TestCase):
    def test_manifest_and_core_business_facts(self) -> None:
        manifest = load_json("demo_manifest.json")
        self.assertEqual(manifest["data_source_type"], "demo_data")
        self.assertFalse(manifest["approval_data_allowed"])
        self.assertFalse(manifest["live_allowed"])
        self.assertFalse(manifest["today_label_allowed"])

        snapshot = load_json("business_snapshot.json")
        self.assertEqual(snapshot["hotel_id"], manifest["hotel_id"])
        self.assertEqual(snapshot["hotel_name"], manifest["hotel_name"])
        self.assertEqual(snapshot["total_rooms"], 50)
        self.assertEqual(snapshot["sold_rooms"], 34)
        self.assertEqual(snapshot["occupancy_rate"], 68)
        self.assertEqual(snapshot["adr"], 188)
        self.assertEqual(snapshot["revpar"], 128)

    def test_room_types_support_s5_s6(self) -> None:
        room_types = load_json("room_types.json")["room_types"]
        self.assertGreaterEqual(len(room_types), 8)
        self.assertEqual(sum(item["inventory"] for item in room_types), 50)
        self.assertEqual(sum(item["sold_rooms"] for item in room_types), 34)
        king = next(item for item in room_types if item["room_type_id"] == "KING")
        for field in ["current_price", "floor_price", "ceiling_price", "inventory", "candidate_price", "conservative_price", "max_single_change_pct"]:
            self.assertIn(field, king)
        self.assertEqual(king["floor_price"], 158)
        self.assertEqual(king["ceiling_price"], 238)
        self.assertEqual(king["conservative_price"], 199)
        for item in room_types:
            with self.subTest(room=item["room_type_id"]):
                self.assertNotIn("?", item["room_type_name"])
                self.assertTrue(any("\u4e00" <= char <= "\u9fff" for char in item["room_type_name"]))

    def test_demo_fact_volume_is_rich_enough_for_full_chain_demo(self) -> None:
        self.assertGreaterEqual(len(load_json("competitors.json")["competitors"]), 5)
        self.assertGreaterEqual(len(load_json("reputation.json")["reviews"]), 20)
        self.assertGreaterEqual(len(load_json("customer_segments.json")["segments"]), 5)
        price_history = load_json("price_history.json")["price_history"]
        room_ids = {item["room_type_id"] for item in load_json("room_types.json")["room_types"]}
        for room_id in room_ids:
            with self.subTest(room=room_id):
                self.assertGreaterEqual(len([row for row in price_history if row["room_type_id"] == room_id]), 7)
        orders = load_json("orders_aggregate.json")
        self.assertGreaterEqual(len(orders["hourly_order_progress"]), 8)
        self.assertTrue((DEMO / "messages" / "message_previews.json").exists())
        self.assertTrue((DEMO / "experience" / "experience_candidates.json").exists())

    def test_static_demo_fixtures_do_not_keep_question_mark_placeholders(self) -> None:
        for name in ["competitors.json", "customer_segments.json", "market_context.json", "reputation.json"]:
            with self.subTest(name=name):
                text = (DEMO / name).read_text(encoding="utf-8")
                self.assertNotIn("????", text)
                self.assertNotIn("\ufffd", text)

    def test_static_sales_progress_fixtures_include_v27_time_aware_fields(self) -> None:
        baseline = load_json("sales_baseline.json")
        progress = load_json("progress_deviation.json")

        for field in [
            "daily_target_room_nights",
            "sample_target_room_nights",
            "active_target_source",
            "hourly_target_curve",
            "checkpoint_targets",
        ]:
            with self.subTest(field=field):
                self.assertIn(field, baseline)
        self.assertEqual(baseline["active_target_source"], "static_demo_fixture")

        for field in [
            "hourly_business_snapshots",
            "as_of_time",
            "as_of_actual_sold_rooms",
            "as_of_target_sold_rooms",
            "as_of_checkpoint_gap",
            "daily_remaining_gap",
            "pickup_speed",
        ]:
            with self.subTest(field=field):
                self.assertIn(field, progress)
        self.assertGreaterEqual(len(progress["hourly_business_snapshots"]), 8)
        for snapshot in progress["hourly_business_snapshots"]:
            with self.subTest(snapshot=snapshot.get("as_of_time")):
                self.assertEqual(snapshot["data_source_type"], "demo_data")
                self.assertEqual(snapshot["freshness_status"], "demo_data")
                self.assertIn("target_sold_rooms", snapshot)

    def test_required_fact_files_exist_for_p2_demo_skills(self) -> None:
        for name in [
            "orders_aggregate.json",
            "price_history.json",
            "sales_baseline.json",
            "progress_deviation.json",
            "competitors.json",
            "market_context.json",
            "reputation.json",
            "promotion.json",
            "customer_segments.json",
            "execution_preview.json",
            "external_ota_report_fields.json",
        ]:
            self.assertTrue((DEMO / name).exists(), name)

    def test_node_and_scenario_fixtures_cover_every_registered_flow_point(self) -> None:
        expected_nodes = {f"N{index:03d}" for index in range(1, 23)}
        expected_scenarios = {f"SC{index:02d}" for index in range(1, 11)}
        node_files = {path.stem for path in (DEMO / "nodes").glob("N*.json")}
        scenario_files = {path.stem for path in (DEMO / "scenarios").glob("SC*.json")}
        self.assertEqual(node_files, expected_nodes)
        self.assertEqual(scenario_files, expected_scenarios)

        covered_nodes: set[str] = set()
        for scenario_id in expected_scenarios:
            scenario = json.loads((DEMO / "scenarios" / f"{scenario_id}.json").read_text(encoding="utf-8"))
            self.assertFalse(scenario.get("placeholder"), scenario_id)
            covered_nodes.update(scenario.get("nodes") or [])
        self.assertEqual(covered_nodes, expected_nodes)
