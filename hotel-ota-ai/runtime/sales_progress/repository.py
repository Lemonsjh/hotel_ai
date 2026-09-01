from __future__ import annotations

import os
import re
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")

MEITUAN_METRICS = {
    "FLOW_EXPOSURE_UV": ("exposure_uv", {"人", "person", "uv", None}),
    "FLOW_INTENTION_UV": ("browse_uv", {"人", "person", "uv", None}),
    "FLOW_PAY_ORDER_CNT": ("paid_orders", {"单", "order", "orders", None}),
    "FLOW_INTENTION_PER_EXPOSURE": ("source_first_conversion", {"%", "ratio", None}),
    "FLOW_PAY_ORDER_PER_INTENTION": ("source_second_conversion", {"%", "ratio", None}),
    "EXPOSE_PV_CNT": ("exposure_impressions", {"次", "count", None}),
    "INTENTION_UV": ("browse_uv_duplicate", {"人", "person", "uv", None}),
    "PAY_ORDER_CNT": ("paid_orders_duplicate", {"单", "order", "orders", None}),
    "PAY_ORDER_CNT_UV": ("source_pay_conversion_duplicate", {"%", "ratio", None}),
    "PAY_ROOMNIGHT": ("paid_room_nights", {"间夜", "room_night", None}),
    "PAY_AMT": ("paid_amount", {"元", "currency", "cny", None}),
    "PAY_ADR": ("paid_adr", {"元", "currency", "cny", None}),
    "DAY_ROOM_LOWEST_PRICE_AVG": ("lead_price_metric", {"元", "currency", "cny", None}),
    "NOT_AVAILABLE_REAL_ROOM_RATE": ("not_available_room_rate", {"%", "ratio", None}),
}

CTRIP_METRICS = {
    "list_page_exposure_count": ("list_exposure_count", {"count", "次", None}),
    "detail_page_visitor_count": ("detail_visitor_count", {"person", "人", None}),
    "order_submit_count": ("submitted_orders", {"order", "orders", "单", None}),
    "exposure_conversion_rate": ("source_list_to_detail_rate", {"%", "ratio", None}),
    "order_conversion_rate": ("source_detail_to_submit_rate", {"%", "ratio", None}),
    "booking_order_count": ("booking_orders", {"order", "orders", "单", None}),
    "booking_sales_amount": ("booking_sales_amount", {"currency", "cny", "元", None}),
    "ctrip_app_visitor_count": ("app_visitors", {"person", "人", None}),
    "ctrip_app_conversion_rate": ("app_conversion_rate", {"%", "ratio", None}),
}


class RepositoryError(RuntimeError):
    pass


def _dsn_for_hotel(hotel_id: str) -> str | None:
    suffix = re.sub(r"[^A-Za-z0-9]", "_", str(hotel_id)).upper()
    return (
        os.environ.get(f"HOTEL_OTA_DB_DSN_{suffix}")
        or os.environ.get("HOTEL_OTA_DB_DSN")
        or None
    )


class DirectSalesProgressRepository:
    def __init__(self, connection: Any):
        self.connection = connection

    @classmethod
    def from_environment(cls, hotel_id: str) -> "DirectSalesProgressRepository":
        dsn = _dsn_for_hotel(hotel_id)
        if not dsn:
            raise RepositoryError("business_database_dsn_missing")
        parsed = urlparse(dsn)
        if parsed.scheme not in {"mysql", "mysql+pymysql"}:
            raise RepositoryError("business_database_dsn_must_be_mysql")
        try:
            import pymysql
        except ImportError as exc:
            raise RepositoryError("pymysql_not_installed") from exc
        connection = pymysql.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=(parsed.path or "").lstrip("/"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            read_timeout=30,
            write_timeout=30,
        )
        return cls(connection)

    def close(self) -> None:
        close = getattr(self.connection, "close", None)
        if callable(close):
            close()

    def _query(self, sql: str, params: Iterable[Any]) -> list[dict[str, Any]]:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall() or []
        except Exception as exc:
            raise RepositoryError(f"query_failed:{type(exc).__name__}") from exc
        return [dict(row) for row in rows]

    def current_forecast(
        self, hotel_id: str, stay_date: str, as_of_datetime: str
    ) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT hotel_id, stay_date, snapshot_time, room_type_id, room_type_name,
                   pms_room_type_id, total_rooms, available_rooms, occupied_rooms,
                   overbooking_rooms, room_revenue, adr, revpar
            FROM pms_room_type_forecast
            WHERE hotel_id=%s AND stay_date=%s AND snapshot_time<=%s
            ORDER BY snapshot_time DESC
            """,
            (hotel_id, stay_date, as_of_datetime),
        )

    def hourly_history(
        self,
        hotel_id: str,
        start_date: str,
        end_date: str,
        as_of_datetime: str,
    ) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT id, hotel_id, stay_date, snapshot_hour, snapshot_time, room_type_id,
                   room_type_name, pms_room_type_id, total_rooms, available_rooms,
                   occupied_rooms, overbooking_rooms
            FROM pms_room_type_hourly_status
            WHERE hotel_id=%s AND stay_date BETWEEN %s AND %s AND snapshot_time<=%s
            ORDER BY stay_date, snapshot_hour, snapshot_time, id
            """,
            (hotel_id, start_date, end_date, as_of_datetime),
        )

    def room_daily(
        self,
        hotel_id: str,
        start_date: str,
        end_date: str,
        as_of_datetime: str,
    ) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT * FROM (
              SELECT hotel_id, business_date, room_type_id, room_type_name,
                     pms_room_type_id, pms_rate_room_type_id, room_nights,
                     occupancy_rate, room_revenue, adr, revpar, snapshot_time,
                     ROW_NUMBER() OVER (
                       PARTITION BY hotel_id, business_date, room_type_id
                       ORDER BY snapshot_time DESC
                     ) AS rn
              FROM jl01_room_type_performance_daily
              WHERE hotel_id=%s AND business_date BETWEEN %s AND %s
                AND snapshot_time<=%s
            ) ranked WHERE rn=1
            """,
            (hotel_id, start_date, end_date, as_of_datetime),
        )

    def hotel_daily_total(
        self,
        hotel_id: str,
        start_date: str,
        end_date: str,
        as_of_datetime: str,
    ) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT * FROM (
              SELECT hotel_id, hotel_name, source_platform, business_date,
                     dimension_type, dimension_name, room_type_id, room_count,
                     room_nights, room_revenue, occupancy_rate, adr, revpar,
                     sold_rooms, remaining_rooms, orders_today, snapshot_time,
                     ROW_NUMBER() OVER (
                       PARTITION BY hotel_id, source_platform, business_date,
                                    dimension_type, dimension_name
                       ORDER BY snapshot_time DESC
                     ) AS rn
              FROM jy01_hotel_statistics_daily
              WHERE hotel_id=%s AND business_date BETWEEN %s AND %s
                AND dimension_type='总营业指标'
                AND dimension_name='总营业指标'
                AND snapshot_time<=%s
            ) ranked WHERE rn=1
            """,
            (hotel_id, start_date, end_date, as_of_datetime),
        )

    def room_revenue(
        self,
        hotel_id: str,
        start_date: str,
        end_date: str,
        as_of_datetime: str,
    ) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT business_date, room_type_id, room_daily_price,
                   SUM(room_nights) AS room_nights,
                   SUM(room_fee) AS room_fee,
                   MAX(snapshot_time) AS snapshot_time
            FROM (
              SELECT id, business_date, room_type_id, room_daily_price,
                     room_nights, room_fee, snapshot_time,
                     ROW_NUMBER() OVER (
                       PARTITION BY hotel_id, business_date, order_id, room_no,
                                    charge_subject, room_type_id
                       ORDER BY snapshot_time DESC, id DESC
                     ) AS rn
              FROM rs01_room_revenue_daily
              WHERE hotel_id=%s AND business_date BETWEEN %s AND %s
                AND room_type_id IS NOT NULL
                AND room_daily_price>0 AND room_nights>0
                AND snapshot_time<=%s
            ) latest
            WHERE rn=1
            GROUP BY business_date, room_type_id, room_daily_price
            """,
            (hotel_id, start_date, end_date, as_of_datetime),
        )

    def ota_business_metrics(
        self,
        platform: str,
        hotel_id: str,
        start_date: str,
        end_date: str,
        as_of_datetime: str,
    ) -> list[dict[str, Any]]:
        table = f"{platform}_ota_business_metrics"
        if not SAFE_IDENTIFIER.fullmatch(table):
            raise RepositoryError("unsafe_metric_table")
        peer_columns = (
            ", peer_average, competitor_rank"
            if str(platform).strip().lower() == "meituan"
            else ""
        )
        return self._query(
            f"""
            SELECT * FROM (
              SELECT id, hotel_id, business_date, snapshot_time, metric_code,
                     metric_name, metric_value, metric_unit, compare_label,
                     compare_value{peer_columns},
                     ROW_NUMBER() OVER (
                       PARTITION BY hotel_id, business_date, metric_code
                       ORDER BY snapshot_time DESC
                     ) AS rn
              FROM {table}
              WHERE hotel_id=%s AND business_date BETWEEN %s AND %s
                AND snapshot_time<=%s
            ) ranked WHERE rn=1
            """,
            (hotel_id, start_date, end_date, as_of_datetime),
        )

    def gross_booking_curve(
        self,
        hotel_id: str,
        start_date: str,
        end_date: str,
        as_of_datetime: str,
    ) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT DATE(arrival_time) AS stay_date,
                   HOUR(booking_time) AS booking_hour,
                   SUM(COALESCE(room_count, 1)) AS gross_created_rooms,
                   COUNT(*) AS booking_rows
            FROM jd01_booking_detail
            WHERE hotel_id=%s
              AND DATE(arrival_time) BETWEEN %s AND %s
              AND booking_time<=%s
            GROUP BY DATE(arrival_time), HOUR(booking_time)
            ORDER BY stay_date, booking_hour
            """,
            (hotel_id, start_date, end_date, as_of_datetime),
        )

    def ctrip_userprofile_hour_distribution(
        self, hotel_id: str, as_of_datetime: str
    ) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT hotel_id, platform_scope, snapshot_time, dimension_code,
                   bucket_label, rate_pct, metric_value, metric_unit, rank_position
            FROM ctrip_ota_userprofile_distribution
            WHERE hotel_id=%s
              AND dimension_code='order_hourly_distribution'
              AND snapshot_time<=%s
            ORDER BY snapshot_time DESC, bucket_label
            """,
            (hotel_id, as_of_datetime),
        )

    def ctrip_competition_metrics_30d(
        self, hotel_id: str, as_of_datetime: str
    ) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT hotel_id, metric_code, metric_name, metric_unit,
                   period_start_date, period_end_date, hotel_value, previous_value,
                   competitor_avg, competitor_rank, previous_rank,
                   competition_circle_hotel_count, snapshot_time
            FROM ctrip_ota_competition_metrics_30d
            WHERE hotel_id=%s AND snapshot_time<=%s
            ORDER BY snapshot_time DESC, metric_code
            """,
            (hotel_id, as_of_datetime),
        )

    def flow_30d(
        self, platform: str, hotel_id: str, as_of_datetime: str
    ) -> list[dict[str, Any]]:
        table = f"{platform}_ota_flow_conversion_30d"
        if not SAFE_IDENTIFIER.fullmatch(table):
            raise RepositoryError("unsafe_flow_table")
        return self._query(
            f"SELECT * FROM {table} WHERE hotel_id=%s AND snapshot_time<=%s "
            "ORDER BY snapshot_time DESC LIMIT 3",
            (hotel_id, as_of_datetime),
        )
