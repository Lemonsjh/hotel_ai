from __future__ import annotations

import argparse
import unittest
from unittest.mock import MagicMock, patch

from runtime.s15_cache_materialization_patch import _materialize_if_missing


class S15CacheMaterializationTest(unittest.TestCase):
    def args(self):
        return argparse.Namespace(
            hotel_id="hotel-a",
            date="2026-08-04",
            db=":memory:",
            use_generated_today=False,
            strict_generated_today=False,
        )

    @patch("runtime.sales_progress.calendar.load_calendar_contexts", return_value={})
    @patch("runtime.sales_progress.DirectSalesProgressRepository.from_environment")
    @patch("runtime.decisions.baseline._persist")
    @patch("runtime.decisions.baseline.build_baseline")
    @patch("runtime.decisions.baseline._cached_baseline", return_value=None)
    def test_cache_miss_builds_and_persists_once(
        self,
        cached,
        build,
        persist,
        from_environment,
        load_calendar,
    ):
        repository = MagicMock()
        from_environment.return_value = repository
        build.return_value = {
            "status": "ok",
            "baseline_package_version": "s15-baseline-package.v1",
            "baseline_package": {"status": "ok"},
        }

        self.assertTrue(_materialize_if_missing(self.args()))
        build.assert_called_once()
        persist.assert_called_once()
        repository.close.assert_called_once()

    @patch("runtime.sales_progress.DirectSalesProgressRepository.from_environment")
    @patch(
        "runtime.decisions.baseline._cached_baseline",
        return_value={"status": "ok", "baseline_package": {}},
    )
    def test_cache_hit_does_not_rebuild(self, cached, from_environment):
        self.assertFalse(_materialize_if_missing(self.args()))
        from_environment.assert_not_called()


if __name__ == "__main__":
    unittest.main()
