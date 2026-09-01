from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV27ContractSchema(unittest.TestCase):
    def test_validate_v27_contract_command_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "tools/validate_v27_contract.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["error_count"], 0)

    def test_contract_json_is_current_machine_contract(self) -> None:
        contract = json.loads((ROOT / "contracts" / "v27" / "contract.json").read_text(encoding="utf-8"))
        self.assertTrue(contract["metadata"]["machine_readable"])
        self.assertIn("V27", contract["metadata"]["contract_version"])
        self.assertEqual(len(contract["agents"]), 7)
        self.assertEqual(len(contract["skills"]), 18)
        self.assertEqual(len(contract["nodes"]), 22)
        self.assertEqual(len(contract["edges"]), 67)
        self.assertEqual(len(contract["scenarios"]), 10)
