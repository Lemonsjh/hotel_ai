from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v40 import fix_score_axis_titles


class ScoreAxisTitleV62Tests(unittest.TestCase):
    def test_moves_hos_and_information_titles_away_from_top_tick(self):
        html = (
            "<html><head></head><body>"
            "<svg class='hos-v2-svg'>"
            "<text class='hos-v2-axis-label' x='58' y='26'>6.10</text>"
            "<text class='hos-v2-axis-label' x='12' y='28'>HOS分</text>"
            "</svg>"
            "<svg class='information-score-svg'>"
            "<text class=\"score-axis-label\" x=\"58\" y=\"26\">100</text>"
            "<text class=\"score-axis-label\" x=\"12\" y=\"28\">信息分</text>"
            "</svg></body></html>"
        )

        rendered = fix_score_axis_titles(html)

        self.assertIn("SCORE_AXIS_TITLE_V62", rendered)
        self.assertIn(
            "class='hos-v2-axis-label score-axis-title-v62' x='68' y='6' "
            "text-anchor='start' dominant-baseline='hanging'>HOS分</text>",
            rendered,
        )
        self.assertIn(
            'class="score-axis-label score-axis-title-v62" x=\'68\' y=\'6\' '
            "text-anchor='start' dominant-baseline='hanging'>信息分</text>",
            rendered,
        )
        self.assertIn("x='58' y='26'>6.10</text>", rendered)
        self.assertIn('x="58" y="26">100</text>', rendered)

    def test_rewrite_is_idempotent(self):
        html = (
            "<html><head></head><body><svg>"
            "<text class='hos-v2-axis-label' x='12' y='28'>HOS分</text>"
            "</svg></body></html>"
        )

        once = fix_score_axis_titles(html)
        twice = fix_score_axis_titles(once)

        self.assertEqual(once, twice)
        self.assertEqual(twice.count("SCORE_AXIS_TITLE_V62"), 1)
        self.assertEqual(twice.count("score-axis-title-v62"), 2)


if __name__ == "__main__":
    unittest.main()
