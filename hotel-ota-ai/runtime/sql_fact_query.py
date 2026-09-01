from __future__ import annotations

import argparse
import os
import re
from typing import Any

from runtime.adapters import database
from runtime.common import emit


VERSION = "sql-fact-fallback.v1"
MAX_ROWS = 200
QUERY_TIMEOUT_MS = 20000

_COMMENT_MARKERS = ("--", "/*", "*/", "#")
_FORBIDDEN_SQL = re.compile(
    r"\b(?:insert|update|delete|replace|alter|drop|create|truncate|call|grant|revoke|"
    r"load|outfile|dumpfile|sleep|benchmark|get_lock|release_lock|procedure|union|with)\b",
    re.IGNORECASE,
)
_TABLE_REF = re.compile(r"\bfrom\s+`?([A-Za-z0-9_]+)`?", re.IGNORECASE)
_HOTEL_SCOPE = re.compile(
    r"(?:`?[A-Za-z0-9_]+`?\.)?`?hotel_id`?\s*=\s*:hotel_id\b",
    re.IGNORECASE,
)
_LIMIT = re.compile(r"\blimit\s+(\d+)\s*$", re.IGNORECASE)
_SELECT_CLAUSE = re.compile(r"^\s*select\s+(.*?)\s+from\s+", re.IGNORECASE | re.DOTALL)


class FactSqlBlocked(ValueError):
    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def _block(reason: str, detail: str | None = None) -> None:
    raise FactSqlBlocked(reason, detail)


def _prepare_fact_sql(sql: str) -> dict[str, str]:
    """Validate one narrow, hotel-scoped SELECT and return executable SQL.

    This is intentionally smaller than a general SQL interface. It exists only as
    a terminal fallback for simple factual questions that native Skills cannot
    answer. Complex joins, subqueries, CTEs and writes remain outside this path.
    """

    statement = str(sql or "").strip()
    if not statement:
        _block("sql_required")
    if statement.endswith(";"):
        statement = statement[:-1].rstrip()
    if ";" in statement:
        _block("multiple_statements_not_allowed")
    if any(marker in statement for marker in _COMMENT_MARKERS):
        _block("sql_comments_not_allowed")
    if not re.match(r"^select\b", statement, re.IGNORECASE):
        _block("select_only")
    if len(re.findall(r"\bselect\b", statement, re.IGNORECASE)) != 1:
        _block("subqueries_not_allowed")
    if _FORBIDDEN_SQL.search(statement):
        _block("forbidden_sql_token")
    if re.search(r"\bjoin\b", statement, re.IGNORECASE):
        _block("joins_not_allowed_v1")
    if re.search(r"\bor\b", statement, re.IGNORECASE):
        _block("or_predicate_not_allowed_v1")
    if "@" in statement or ":=" in statement:
        _block("sql_variables_not_allowed")
    if re.search(r"\bfor\s+update\b|\block\s+in\s+share\s+mode\b", statement, re.IGNORECASE):
        _block("locking_read_not_allowed")

    tables = _TABLE_REF.findall(statement)
    if len(tables) != 1:
        _block("single_table_required")
    table = tables[0]
    database._safe_identifier(table, "table")

    from_tail = re.split(r"\bfrom\b", statement, maxsplit=1, flags=re.IGNORECASE)[1]
    from_head = re.split(
        r"\bwhere\b|\bgroup\s+by\b|\border\s+by\b|\blimit\b",
        from_tail,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    if "," in from_head:
        _block("single_table_required")

    if statement.count(":hotel_id") != 1 or not _HOTEL_SCOPE.search(statement):
        _block("exact_hotel_scope_required", "SQL must contain hotel_id = :hotel_id exactly once")

    select_match = _SELECT_CLAUSE.search(statement)
    if not select_match:
        _block("select_projection_invalid")
    projection = select_match.group(1)
    projection_without_count_star = re.sub(
        r"\bcount\s*\(\s*\*\s*\)",
        "",
        projection,
        flags=re.IGNORECASE,
    )
    if "*" in projection_without_count_star:
        _block("wildcard_projection_not_allowed")

    limit_match = _LIMIT.search(statement)
    if limit_match:
        if int(limit_match.group(1)) > MAX_ROWS:
            _block("row_limit_exceeded", f"LIMIT must be <= {MAX_ROWS}")
    else:
        statement = f"{statement} LIMIT {MAX_ROWS}"

    executable = re.sub(
        r"^\s*select\b",
        f"SELECT /*+ MAX_EXECUTION_TIME({QUERY_TIMEOUT_MS}) */",
        statement,
        count=1,
        flags=re.IGNORECASE,
    ).replace(":hotel_id", "%s")
    return {
        "table": table,
        "statement": statement,
        "executable": executable,
    }


def _load_table_columns(conn: Any, table: str) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COLUMN_NAME AS column_name
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            (table,),
        )
        return [str(row.get("column_name") or "") for row in cursor.fetchall()]


def _sensitive_column_references(sql: str, columns: list[str]) -> list[str]:
    references: list[str] = []
    for column in columns:
        lowered = column.lower()
        if not any(pattern in lowered for pattern in database.SENSITIVE_FIELD_PATTERNS):
            continue
        if re.search(
            rf"(?<![A-Za-z0-9_])`?{re.escape(column)}`?(?![A-Za-z0-9_])",
            sql,
            re.IGNORECASE,
        ):
            references.append(column)
    return references


def query_fact_sql(
    *,
    hotel_id: str,
    sql: str,
    profile: str | None = None,
    mapping_config: str | None = None,
    dsn: str | None = None,
) -> dict[str, Any]:
    if not str(hotel_id or "").strip():
        return {"status": "blocked", "reason": "hotel_id_required", "version": VERSION}
    if os.environ.get("HOTEL_OTA_DB_READONLY", "1") != "1":
        return {
            "status": "blocked",
            "reason": "database_adapter_requires_readonly",
            "version": VERSION,
        }

    try:
        prepared = _prepare_fact_sql(sql)
    except FactSqlBlocked as exc:
        return {
            "status": "blocked",
            "reason": exc.reason,
            "detail": exc.detail,
            "version": VERSION,
            "fallback_terminal": True,
            "write_performed": False,
        }

    config = database._load_mapping_config(mapping_config)
    selected_profile = database._profile(config, profile)
    args = argparse.Namespace(
        db_kind="mysql",
        hotel_id=hotel_id,
        profile=profile,
        mapping_config=mapping_config,
        dsn=dsn,
    )
    try:
        conn, blocked = database._connect_mysql(args, selected_profile)
    except (KeyError, ValueError) as exc:
        return {
            "status": "blocked",
            "reason": "database_connection_config_invalid",
            "error_type": exc.__class__.__name__,
            "version": VERSION,
            "fallback_terminal": True,
            "write_performed": False,
        }
    if blocked:
        return {
            **blocked,
            "version": VERSION,
            "fallback_terminal": True,
            "write_performed": False,
        }
    assert conn is not None

    try:
        with conn:
            columns = _load_table_columns(conn, prepared["table"])
            if not columns:
                return {
                    "status": "blocked",
                    "reason": "fact_table_not_found",
                    "source_table": prepared["table"],
                    "version": VERSION,
                    "fallback_terminal": True,
                    "write_performed": False,
                }
            if "hotel_id" not in {column.lower() for column in columns}:
                return {
                    "status": "blocked",
                    "reason": "fact_table_not_hotel_scoped",
                    "source_table": prepared["table"],
                    "version": VERSION,
                    "fallback_terminal": True,
                    "write_performed": False,
                }
            sensitive = _sensitive_column_references(prepared["statement"], columns)
            if sensitive:
                return {
                    "status": "blocked",
                    "reason": "sensitive_columns_not_allowed",
                    "source_table": prepared["table"],
                    "sensitive_column_count": len(sensitive),
                    "version": VERSION,
                    "fallback_terminal": True,
                    "write_performed": False,
                }

            with conn.cursor() as cursor:
                cursor.execute(prepared["executable"], (hotel_id,))
                rows = [database._redact_row(dict(row)) for row in cursor.fetchall()]
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": "fact_query_failed",
            "error_type": exc.__class__.__name__,
            "source_table": prepared["table"],
            "version": VERSION,
            "fallback_terminal": True,
            "write_performed": False,
        }

    return {
        "status": "ok" if rows else "no_rows",
        "capability": "sql_fact_fallback",
        "version": VERSION,
        "hotel_id": hotel_id,
        "source_type": "mysql_db",
        "source_table": prepared["table"],
        "row_count": len(rows),
        "rows": rows,
        "query_shape": prepared["statement"],
        "max_rows": MAX_ROWS,
        "query_timeout_hint_ms": QUERY_TIMEOUT_MS,
        "fallback_terminal": True,
        "free_sql_allowed": False,
        "write_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-shot, read-only SQL fallback for simple hotel factual questions."
    )
    parser.add_argument("--hotel-id", required=True)
    parser.add_argument("--sql", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--mapping-config")
    parser.add_argument("--dsn")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = query_fact_sql(
        hotel_id=args.hotel_id,
        sql=args.sql,
        profile=args.profile,
        mapping_config=args.mapping_config,
        dsn=args.dsn,
    )
    emit(result)
    return 0 if result.get("status") in {"ok", "no_rows"} else 2


if __name__ == "__main__":
    raise SystemExit(main())