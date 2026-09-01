from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime import demo_mode


class TestDemoNoPlaceholderByDefault(unittest.TestCase):
    def test_missing_node_fixture_fails_without_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nodes").mkdir()
            with mock.patch.object(demo_mode, "DEMO_DATA_DIR", root):
                result = demo_mode.build_all_demo_nodes_result(allow_placeholder=False)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["passed_nodes"], 0)
        self.assertEqual(result["failed_nodes"], 22)

    def test_missing_scenario_fixture_fails_without_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scenarios").mkdir()
            with mock.patch.object(demo_mode, "DEMO_DATA_DIR", root):
                result = demo_mode.build_all_demo_chains_result(allow_placeholder=False)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["passed_scenarios"], 0)
        self.assertEqual(result["failed_scenarios"], 10)

    def test_explicit_placeholder_does_not_count_as_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nodes").mkdir()
            with mock.patch.object(demo_mode, "DEMO_DATA_DIR", root):
                result = demo_mode.build_all_demo_nodes_result(allow_placeholder=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["passed_nodes"], 0)
        self.assertEqual(result["failed_nodes"], 22)
        self.assertTrue(all(node.get("placeholder") for node in result["nodes"]))
