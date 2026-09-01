from __future__ import annotations

import unittest
from unittest.mock import patch

from marketing_diagnosis import reporting_v27


class ScanInformationStackedLayoutTests(unittest.TestCase):
    def test_items_07_and_08_are_stacked_as_full_width_rows(self):
        base_html = (
            "<html><head></head><body>"
            "<div class='diagnosis-pair-v17'>"
            "<article class='diagnosis-card' id='rule-7'>扫码订单数据</article>"
            "<article class='diagnosis-card' id='rule-8'>信息分数据</article>"
            "</div></body></html>"
        )
        with patch.object(reporting_v27.reporting_v26, "build_html", return_value=base_html):
            html = reporting_v27.build_html({})

        self.assertIn("grid-template-columns:minmax(0,1fr)!important", html)
        self.assertIn("id='rule-7'", html)
        self.assertIn("id='rule-8'", html)
        self.assertIn("width:100%", html)


if __name__ == "__main__":
    unittest.main()
