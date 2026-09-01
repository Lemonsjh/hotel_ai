from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator


VERSION = "s2-business-metric-snapshot.v1"
_USE_PER_METRIC_SNAPSHOT: ContextVar[bool] = ContextVar(
    "s2_use_per_metric_business_snapshot",
    default=False,
)
_INSTALLED = False


def _per_metric_snapshot_clause(
    table: str,
    columns: dict[str, str],
    scope_parts: list[str],
    scope_params: list[Any],
) -> tuple[str, list[Any]]:
    """Keep the latest snapshot independently for each metric_code in scope."""
    snapshot_col = columns.get("snapshot_time")
    metric_col = columns.get("metric_code")
    if not snapshot_col or not metric_col:
        return "", []

    # Reuse the adapter's identifier guard so this patch never opens a free-SQL path.
    from runtime.adapters.database import _safe_identifier

    safe_table = _safe_identifier(table, "table")
    safe_snapshot = _safe_identifier(snapshot_col, "column")
    safe_metric = _safe_identifier(metric_col, "column")
    return (
        f"({safe_metric}, {safe_snapshot}) IN ("
        f"SELECT {safe_metric}, MAX({safe_snapshot}) FROM {safe_table} "
        f"WHERE {' AND '.join(scope_parts)} GROUP BY {safe_metric})",
        list(scope_params),
    )


def install() -> None:
    """Patch snapshot selection, but activate it only inside S2's scoped context."""
    global _INSTALLED
    if _INSTALLED:
        return

    from runtime.adapters import database as db

    previous = db._latest_snapshot_clause
    if getattr(previous, "_S2_PER_METRIC_BUSINESS_SNAPSHOT_V1", False):
        _INSTALLED = True
        return

    def _latest_snapshot_clause(
        table: str,
        columns: dict[str, str],
        scope_parts: list[str],
        scope_params: list[Any],
    ) -> tuple[str, list[Any]]:
        if (
            _USE_PER_METRIC_SNAPSHOT.get()
            and columns.get("metric_code")
            and columns.get("snapshot_time")
        ):
            return _per_metric_snapshot_clause(
                table,
                columns,
                scope_parts,
                scope_params,
            )
        return previous(table, columns, scope_parts, scope_params)

    _latest_snapshot_clause._S2_PER_METRIC_BUSINESS_SNAPSHOT_V1 = True  # type: ignore[attr-defined]
    db._latest_snapshot_clause = _latest_snapshot_clause
    _INSTALLED = True


@contextmanager
def s2_business_metric_snapshot_scope() -> Iterator[None]:
    """Enable per-metric latest-snapshot semantics for one S2 source query only."""
    install()
    token = _USE_PER_METRIC_SNAPSHOT.set(True)
    try:
        yield
    finally:
        _USE_PER_METRIC_SNAPSHOT.reset(token)
