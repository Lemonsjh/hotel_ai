from __future__ import annotations

import unittest

from runtime.s16_skill_delivery_patch import build_s16_response_contract


class S16RuntimeKnowledgeIndexTests(unittest.TestCase):
    def test_contract_uses_authoritative_index_and_preserves_advisories(self):
        result = {
            "dynamic_diagnosis": {
                "room_structure": {
                    "room_type_results": [
                        {
                            "room_type_id": "py05",
                            "sales_status": "significant_slow",
                        }
                    ]
                },
                "estimated_price_advisories": [
                    {
                        "ota_product_id": "1146760259",
                        "action_type": "estimated_price_decrease_advisory",
                    }
                ],
            }
        }
        contract = build_s16_response_contract(result)
        self.assertTrue(
            contract["knowledge_file"].endswith(
                "S16_RUNTIME_KNOWLEDGE_INDEX.md"
            )
        )
        self.assertEqual(
            contract["knowledge_precedence"][0],
            contract["knowledge_file"],
        )
        self.assertIn(
            "S16_MEITUAN_DAILY_PROJECTION_AND_ADVISORY_RULES.md",
            "\n".join(contract["knowledge_files"]),
        )
        self.assertEqual(contract["anomalous_room_type_ids"], ["py05"])
        self.assertEqual(
            contract["advisory_ota_product_ids"],
            ["1146760259"],
        )
        self.assertTrue(contract["must_preserve_price_advisories"])


if __name__ == "__main__":
    unittest.main()
