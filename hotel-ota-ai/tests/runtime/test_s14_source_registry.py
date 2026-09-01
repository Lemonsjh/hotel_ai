from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_command_router import safe_route_feishu_command
from runtime.s14_source_registry import resolve_s14_source


class TestS14SourceRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.config_path = root / "s14-source.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "hotels": {
                        "puyue": {
                            "s14_sources": {
                                "monthly_excel": {
                                    "source_mode": "excel",
                                    "path": str(root / "missing-monthly.xlsx"),
                                    "enabled": True,
                                },
                                "readonly_mysql": {
                                    "source_mode": "mysql",
                                    "profile": "puyue_mysql_prod",
                                    "enabled": True,
                                },
                            }
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_registry_resolves_only_known_source_keys(self) -> None:
        resolved = resolve_s14_source(str(self.config_path), hotel_id="puyue", source_key="monthly_excel")
        self.assertEqual(resolved["status"], "ok")
        self.assertEqual(resolved["source_mode"], "excel")

        missing = resolve_s14_source(str(self.config_path), hotel_id="puyue", source_key="../secret.xlsx")
        self.assertEqual(missing["status"], "data_gap")
        self.assertEqual(missing["reason"], "s14_source_key_not_registered")

    def test_feishu_s14_source_request_uses_registry_not_arbitrary_path(self) -> None:
        result = safe_route_feishu_command(
            "运行 S14-EXT source=monthly_excel",
            role="owner",
            trusted_runtime_role=True,
            hotel_id="puyue",
            render=True,
            compact=False,
            s14_source_config=str(self.config_path),
        )
        self.assertEqual(result["intent"], "s14_source_request")
        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["blocked_reason"], "s14_ext_migrated_to_independent_service")
        self.assertFalse(result["business_result_generated"])
        self.assertIn("第三方营销诊断已迁移到独立服务", result["send_payload"]["text"])
        self.assertNotIn(str(self.config_path), result["send_payload"]["text"])


if __name__ == "__main__":
    unittest.main()
