from __future__ import annotations

from runtime.s10_promotion_source import S10MySQLSource
from runtime.s11_promotion_source import query_s11_promotion_performance


class CapturingS10Source(S10MySQLSource):
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = list(rows or [])
        self.queries: list[tuple[str, list[object]]] = []

    def _columns(self, table: str) -> set[str]:
        return {
            "hotel_id",
            "period_start_date",
            "period_end_date",
            "snapshot_time",
            "plan_id",
            "plan_name",
            "launch_id",
            "launch_name",
            "promotion_name",
            "promotion_status",
            "spend_amount",
            "booking_order_amount",
        }

    def _query(self, sql: str, params: list[object]) -> list[dict]:
        self.queries.append((sql, list(params)))
        return [dict(row) for row in self.rows]


class FakePerLaunchSource:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, str, str | None, bool]] = []

    def latest_rows(
        self,
        platform: str,
        *,
        hotel_id: str,
        as_of_time: str | None,
        per_launch: bool = False,
    ) -> list[dict]:
        self.calls.append((platform, hotel_id, as_of_time, per_launch))
        return [dict(row) for row in self.rows]


def test_meituan_per_launch_sql_selects_each_launch_latest_snapshot() -> None:
    source = CapturingS10Source()

    source.latest_rows(
        "meituan",
        hotel_id="hotel-a",
        as_of_time="2026-08-10 18:00:00",
        per_launch=True,
    )

    assert len(source.queries) == 1
    sql, params = source.queries[0]
    assert "p2.`hotel_id`=p.`hotel_id`" in sql
    assert "p2.`launch_id`=p.`launch_id`" in sql
    assert "MAX(p2.`snapshot_time`)" in sql
    assert "p.`hotel_id`=%s" in sql
    assert "p.`launch_id` IS NOT NULL" in sql
    assert "p.`snapshot_time`<=%s" in sql
    assert "p2.`snapshot_time`<=%s" in sql
    assert params == ["hotel-a", "2026-08-10 18:00:00", "2026-08-10 18:00:00"]


def test_s11_source_preserves_two_launches_with_different_latest_times() -> None:
    rows = [
        {
            "hotel_id": "hotel-a",
            "plan_id": "090510524719",
            "launch_id": "launch-store",
            "period_end_date": "2026-08-09",
            "snapshot_time": "2026-08-10 09:46:00",
        },
        {
            "hotel_id": "hotel-a",
            "plan_id": "041617192624",
            "launch_id": "launch-fast",
            "period_end_date": "2026-08-09",
            "snapshot_time": "2026-08-10 17:06:00",
        },
    ]
    source = FakePerLaunchSource(rows)

    result = query_s11_promotion_performance(
        "hotel-a",
        as_of_time="2026-08-10 18:00:00",
        source=source,
    )

    payload = result["payload"]
    assert result["status"] == "ok"
    assert payload["snapshot_policy"] == "latest_per_launch"
    assert len(payload["rows"]) == 2
    assert payload["data_snapshot_time"] == "2026-08-10 17:06:00"
    assert payload["launch_snapshot_times"] == {
        "launch-store": "2026-08-10 09:46:00",
        "launch-fast": "2026-08-10 17:06:00",
    }
    assert source.calls == [
        ("meituan", "hotel-a", "2026-08-10 18:00:00", True)
    ]
