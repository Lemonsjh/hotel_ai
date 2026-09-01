from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from runtime.storage import connect, init_schema


class TestCliEntrypoint(unittest.TestCase):
    def test_module_help_prints_usage(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "runtime.cli", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Hotel OTA OpenClaw runtime helper", result.stdout)
        self.assertIn("database-query", result.stdout)

    def test_module_database_query_prints_json(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "runtime.sqlite")
            conn = connect(db_path)
            try:
                init_schema(conn)
                conn.execute(
                    "INSERT INTO hotels (hotel_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    ("hotel-a", "Hotel A", "2026-07-02 00:00:00", "2026-07-02 00:00:00"),
                )
                conn.commit()
            finally:
                conn.close()

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "runtime.cli",
                    "--db",
                    db_path,
                    "database-query",
                    "--db-kind",
                    "sqlite",
                    "--template",
                    "operating_snapshot",
                    "--hotel-id",
                    "hotel-a",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"status": "ok"', result.stdout)
        self.assertIn('"template": "operating_snapshot"', result.stdout)


if __name__ == "__main__":
    unittest.main()
