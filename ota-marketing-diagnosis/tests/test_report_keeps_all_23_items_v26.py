from __future__ import annotations

import re
import unittest

from marketing_diagnosis.reporting_v20 import _remove_old_crown_script


class ReportKeepsAllItemsTest(unittest.TestCase):
    def test_crown_cleanup_does_not_cross_hos_script_boundary(self) -> None:
        cards = "".join(
            f"<article class='diagnosis-card' id='rule-{number}'></article>"
            for number in range(1, 24)
        )
        hos_script = "<script>(function(){const hosChart=true;})();</script>"
        crown_script = (
            "<script>(function(){"
            "document.getElementById('crown-save-button');"
            "const key='s14:crown:test';"
            "})();</script>"
        )
        html = cards.replace(
            "<article class='diagnosis-card' id='rule-7'>",
            hos_script + "<article class='diagnosis-card' id='rule-7'>",
        ) + crown_script

        cleaned = _remove_old_crown_script(html)
        ids = sorted(
            int(value)
            for value in re.findall(r"id=['\"]rule-(\d+)['\"]", cleaned)
        )

        self.assertEqual(ids, list(range(1, 24)))
        self.assertIn("hosChart", cleaned)
        self.assertNotIn("crown-save-button", cleaned)
        self.assertNotIn("s14:crown:test", cleaned)


if __name__ == "__main__":
    unittest.main()
