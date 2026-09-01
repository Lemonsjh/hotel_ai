from __future__ import annotations

import os
import tomllib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_security_and_freshness import _capture_json

from runtime.cli import main


ROOT = Path(__file__).resolve().parents[2]


class TestDependencyAndConfigValidation(unittest.TestCase):
    def test_pyproject_declares_runtime_and_test_entrypoints(self) -> None:
        pyproject = ROOT / "pyproject.toml"
        self.assertTrue(pyproject.exists())
        text = pyproject.read_text(encoding="utf-8")
        self.assertIn('name = "hotel-ota-ai"', text)
        self.assertIn('requires-python = ">=3.11"', text)
        self.assertIn('"python runtime/hotel_ota_runtime.py env-check"', text)
        self.assertIn('"python -m unittest discover tests"', text)

    def test_mysql_inspect_dependency_is_declared_for_deployment(self) -> None:
        pyproject = ROOT / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

        mysql_extra = data["project"]["optional-dependencies"]["mysql"]
        self.assertTrue(any(item.lower().startswith("pymysql") for item in mysql_extra))

    def test_env_check_reports_config_paths_as_booleans_not_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = Path(tmp) / "feishu-role-map.json"
            mapping_path = Path(tmp) / "database-source.json"
            auth_path.write_text('{"users":[],"allowed_chat_ids":[]}', encoding="utf-8")
            mapping_path.write_text('{"profiles":{},"default_profile":"demo"}', encoding="utf-8")
            env = {
                "HOTEL_OTA_DB": str(Path(tmp) / "hotel_ops.sqlite"),
                "HOTEL_OTA_LOG_DIR": tmp,
                "HOTEL_OTA_ENV": "production",
                "HOTEL_OTA_AUTH_CONFIG": str(auth_path),
                "HOTEL_OTA_DB_SOURCE_ENABLE": "0",
                "HOTEL_OTA_DB_KIND": "sqlite",
                "HOTEL_OTA_DB_MAPPING_CONFIG": str(mapping_path),
                "HOTEL_OTA_DB_PROFILE": "demo",
                "HOTEL_OTA_DB_DSN": "",
                "HOTEL_OTA_DB_READONLY": "1",
                "HOTEL_OTA_FEISHU_DEBUG": "0",
                "HOTEL_OTA_FEISHU_FINAL_GATE_REQUIRED": "1",
                "HOTEL_OTA_FEISHU_ALLOW_FILE_EXPORT": "0",
                "HOTEL_OTA_FEISHU_ALLOW_CONFIG_EXPORT": "0",
                "HOTEL_OTA_FEISHU_ALLOW_RAW_DATA_EXPORT": "0",
                "HOTEL_OTA_PRICE_TASK_WRITE_ENABLE": "0",
                "HOTEL_OTA_PRICE_TASK_REQUIRE_CONFIRM": "1",
                "HOTEL_OTA_PRICE_TASK_ALLOWED_CHANNELS": "ctrip,meituan",
                "HOTEL_OTA_MARKET_SOURCE_CONFIG": str(Path(tmp) / "market-source.json"),
                "HOTEL_OTA_S14_SOURCE_CONFIG": str(Path(tmp) / "s14-source.json"),
                "BEYONDH_ENABLE_LIVE": "0",
                "MEITUAN_ENABLE_LIVE": "0",
                "DINDANLL_ENABLE_LIVE": "0",
            }
            Path(env["HOTEL_OTA_MARKET_SOURCE_CONFIG"]).write_text('{"version":2,"hotels":{}}', encoding="utf-8")
            Path(env["HOTEL_OTA_S14_SOURCE_CONFIG"]).write_text('{"version":1,"hotels":{}}', encoding="utf-8")
            with patch.dict(os.environ, env, clear=True):
                result = _capture_json(main, ["env-check"])

        serialized = str(result)
        self.assertNotIn(str(auth_path), serialized)
        self.assertNotIn(str(mapping_path), serialized)
        self.assertNotIn(env["HOTEL_OTA_MARKET_SOURCE_CONFIG"], serialized)
        self.assertNotIn(env["HOTEL_OTA_S14_SOURCE_CONFIG"], serialized)
        self.assertTrue(result["path_status"]["auth_config_exists"])
        self.assertTrue(result["path_status"]["db_mapping_config_exists"])
        self.assertTrue(result["path_status"]["market_source_config_exists"])
        self.assertTrue(result["path_status"]["s14_source_config_exists"])
        self.assertEqual(result["env"]["HOTEL_OTA_S14_SOURCE_CONFIG"], "set")


if __name__ == "__main__":
    unittest.main()
