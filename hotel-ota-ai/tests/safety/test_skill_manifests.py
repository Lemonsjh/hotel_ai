from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestSkillManifests(unittest.TestCase):
    def test_skill_manifest_checker_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/check_skill_manifests.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
