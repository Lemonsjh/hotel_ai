from __future__ import annotations

from typing import Any

from runtime.s10_promotion_source import S10DataGap, S10MySQLSource


TABLE_NAME = "meituan_ota_promotion_performance_30d"
SNAPSHOT_POLICY = "latest_per_launch"


def query_s11_promotion_performance(
    hotel_id: str,
    *,
    as_of_time: str | None = None,
    source: S10MySQLSource | None = None,
) -> dict[str, Any]:
    """Return one latest known Meituan row per launch_id for S11 planning/execution.

    S8 keeps its own display-only global-snapshot contract. S11 needs a complete
    set of currently known promotion instances, so each launch_id is refreshed
    independently and its latest eligible row is selected.
    """
    try:
        source = source or S10MySQLSource.from_env(hotel_id=hotel_id)
        rows = source.latest_rows(
            "meituan",
            hotel_id=hotel_id,
            as_of_time=as_of_time,
            per_launch=True,
        )
    except S10DataGap as exc:
        reason = str(exc)
        return {
            "status": "data_gap",
            "reason": reason,
            "payload": {
                "source_status": "schema_drift" if reason == "source_schema_drift" else "unavailable",
                "source_table": TABLE_NAME,
                "snapshot_policy": SNAPSHOT_POLICY,
                "rows": [],
                "data_snapshot_time": None,
                "data_business_date": None,
                "launch_snapshot_times": {},
            },
        }

    snapshots = [
        str(row["snapshot_time"])
        for row in rows
        if row.get("snapshot_time") not in (None, "")
    ]
    dates = [
        str(row["period_end_date"])
        for row in rows
        if row.get("period_end_date") not in (None, "")
    ]
    launch_snapshot_times = {
        str(row.get("launch_id")): str(row.get("snapshot_time"))
        for row in rows
        if row.get("launch_id") not in (None, "") and row.get("snapshot_time") not in (None, "")
    }
    return {
        "status": "ok",
        "reason": None,
        "payload": {
            "source_status": "ok" if rows else "no_rows",
            "source_table": TABLE_NAME,
            "snapshot_policy": SNAPSHOT_POLICY,
            "rows": rows,
            "data_snapshot_time": max(snapshots) if snapshots else None,
            "data_business_date": max(dates) if dates else None,
            "launch_snapshot_times": launch_snapshot_times,
        },
    }
