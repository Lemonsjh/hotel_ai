from __future__ import annotations

import contextlib
import io
import json
import os
import unittest
from unittest import mock

from runtime.cli import main


class EnvCheckDeprecatedKeysTests(unittest.TestCase):
    def test_deprecated_weather_and_holiday_keys_are_not_missing_config(self) -> None:
        buffer = io.StringIO()
        env = {
            "HOTEL_OTA_ENV": "production",
            "HOTEL_OTA_FEISHU_DEBUG": "0",
            "HOTEL_OTA_FEISHU_FINAL_GATE_REQUIRED": "1",
            "HOTEL_OTA_REQUIRE_VERIFIED_ROLE": "1",
        }
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(buffer):
            main(["env-check"])

        result = json.loads(buffer.getvalue())
        missing = set(result.get("missing_keys") or [])
        self.assertNotIn("OPEN_METEO_API_KEY", missing)
        self.assertNotIn("QWEATHER_API_KEY", missing)
        self.assertNotIn("JIEJIARI_API_KEY", missing)
        self.assertNotIn("JIEJIARI_BASE_URL", missing)


if __name__ == "__main__":
    unittest.main()
