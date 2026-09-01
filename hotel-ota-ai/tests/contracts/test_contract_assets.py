from __future__ import annotations

import unittest

from runtime.field_contract_loader import load_field_registry, load_node_io_contract, load_source_mapping


class TestContractAssets(unittest.TestCase):
    def test_field_registry_uses_v26_status_model(self) -> None:
        registry = load_field_registry()
        statuses = set(registry["supported_statuses"])
        self.assertTrue(
            {
                "confirmed_exact",
                "confirmed_alias",
                "candidate_inferred",
                "project_only",
                "config_only",
                "algorithm_output",
                "upstream_output",
                "manual_required",
                "not_available",
                "deprecated",
            }.issubset(statuses)
        )
        self.assertGreaterEqual(len(registry["fields"]), 290)
        self.assertGreater(len(registry["algorithm_field_requirements"]), 0)

    def test_node_io_contract_covers_all_nodes(self) -> None:
        contract = load_node_io_contract()
        node_ids = {node["node_id"] for node in contract["nodes"]}
        self.assertEqual(node_ids, {f"N{index:03d}" for index in range(1, 23)})

    def test_source_mapping_is_non_secret_v26_inventory(self) -> None:
        mapping = load_source_mapping()
        self.assertGreaterEqual(mapping["source_field_count"], 500)
        serialized = str(mapping).lower()
        self.assertNotIn("password=", serialized)
        self.assertNotIn("api_key=", serialized)
        self.assertNotIn("secret=", serialized)
