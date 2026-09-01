from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import unittest
from unittest import mock

from runtime.adapters import database


class TestDatabaseQueryCliContract(unittest.TestCase):
    def test_database_query_passes_as_of_time_to_template_result(self) -> None:
        old_readonly = os.environ.get("HOTEL_OTA_DB_READONLY")
        os.environ["HOTEL_OTA_DB_READONLY"] = "1"
        try:
            with mock.patch(
                "runtime.adapters.database.database_template_result",
                return_value={"status": "ok", "payload": {}},
            ) as template_result, contextlib.redirect_stdout(io.StringIO()) as output:
                database.database_query(
                    argparse.Namespace(
                        db_kind="mysql",
                        template="reservation_snapshot",
                        hotel_id="puyue",
                        dsn=None,
                        profile=None,
                        mapping_config=None,
                        date="2026-07-04",
                        source_platform=None,
                        as_of_time="2026-07-04 20:14:44",
                        sql=None,
                    )
                )
        finally:
            if old_readonly is None:
                os.environ.pop("HOTEL_OTA_DB_READONLY", None)
            else:
                os.environ["HOTEL_OTA_DB_READONLY"] = old_readonly

        self.assertEqual(json.loads(output.getvalue())["status"], "ok")
        self.assertEqual(template_result.call_args.kwargs["as_of_time"], "2026-07-04 20:14:44")


if __name__ == "__main__":
    unittest.main()
