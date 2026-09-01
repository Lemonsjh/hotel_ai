from __future__ import annotations

from contextlib import closing
from typing import Any


def load_calendar_contexts(
    db_path: str,
    start_date: str,
    end_date: str,
    target_date: str,
) -> dict[str, dict[str, Any]]:
    """Read date labels directly from the local calendar table without calling S4."""
    try:
        from runtime.storage import connect, init_schema

        with closing(connect(db_path)) as conn:
            init_schema(conn)
            rows = conn.execute(
                """
                SELECT date, weekday, is_weekend, is_workday, is_holiday,
                       is_adjusted_workday, holiday_name, holiday_group,
                       season_tag, school_vacation_tag, local_event_count,
                       event_heat_level, source_quality
                FROM calendar_days
                WHERE (date BETWEEN ? AND ?) OR date=?
                """,
                (start_date, end_date, target_date),
            ).fetchall()
    except Exception:
        return {}
    return {str(row["date"]): dict(row) for row in rows}
