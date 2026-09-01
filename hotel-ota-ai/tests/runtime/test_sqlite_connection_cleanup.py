from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from runtime.storage import connect


class BrokenPragmaConnection:
    row_factory = None

    def __init__(self) -> None:
        self.closed = False

    def execute(self, statement: str) -> None:
        if statement == "PRAGMA journal_mode=WAL":
            raise sqlite3.OperationalError("pragma failed")

    def close(self) -> None:
        self.closed = True


class TestSqliteConnectionCleanup(unittest.TestCase):
    def test_connect_closes_connection_when_setup_fails(self) -> None:
        broken = BrokenPragmaConnection()

        with patch("runtime.storage.ensure_dirs"), patch("runtime.storage.sqlite3.connect", return_value=broken):
            with self.assertRaises(sqlite3.OperationalError):
                connect("ignored.sqlite")

        self.assertTrue(broken.closed)
