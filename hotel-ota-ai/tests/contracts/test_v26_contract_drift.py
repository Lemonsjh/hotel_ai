from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV27ContractDrift(unittest.TestCase):
    def test_drift_audit_passes_core_checks(self) -> None:
        result = subprocess.run(
            [sys.executable, "tools/audit_v27_contract_drift.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["P0"], 0)
        self.assertEqual(payload["P1"], 0)
