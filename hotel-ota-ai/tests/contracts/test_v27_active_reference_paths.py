from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.common import PACKAGE_ROOT
from runtime.field_contract_loader import load_field_registry, load_node_io_contract, load_source_mapping


class TestV27ActiveReferencePaths(unittest.TestCase):
    def test_default_contract_loader_reads_v27_assets(self) -> None:
        self.assertGreaterEqual(len(load_field_registry()["fields"]), 290)
        self.assertEqual({node["node_id"] for node in load_node_io_contract()["nodes"]}, {f"N{value:03d}" for value in range(1, 23)})
        self.assertGreaterEqual(load_source_mapping()["source_field_count"], 500)

    def test_active_algorithm_rules_reference_v27_contracts(self) -> None:
        rules_dir = PACKAGE_ROOT / "runtime" / "algorithm_rules"
        for path in rules_dir.glob("*.yaml"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            refs = payload.get("source_refs") or {}
            with self.subTest(rule=path.name):
                self.assertTrue(str(refs.get("field_registry", "")).startswith("contracts/v27/"))
                self.assertTrue(str(refs.get("node_io_contract", "")).startswith("contracts/v27/"))


if __name__ == "__main__":
    unittest.main()
