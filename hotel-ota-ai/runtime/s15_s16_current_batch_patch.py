from __future__ import annotations

from typing import Any

_INSTALLED = False
VERSION = "s15-s16-current-batch.v2"


def current_forecast(
    self: Any,
    hotel_id: str,
    stay_date: str,
    as_of_datetime: str,
) -> list[dict[str, Any]]:
    """Return the latest legal forecast rows for the target stay date.

    `stay_date` is the target business date while `snapshot_time` is only the
    collection time. A collector pause must not turn a real but stale forecast
    into a semantic data gap. The downstream batch selector therefore receives
    every row whose snapshot is not in the future, selects one internally
    consistent room-type batch, records its age, and suppresses actions when it
    is stale.
    """

    return self._query(
        """
        SELECT hotel_id, stay_date, snapshot_time, room_type_id, room_type_name,
               pms_room_type_id, total_rooms, available_rooms, occupied_rooms,
               overbooking_rooms, room_revenue, adr, revpar
        FROM pms_room_type_forecast
        WHERE hotel_id=%s AND stay_date=%s AND snapshot_time<=%s
        ORDER BY snapshot_time DESC, room_type_id
        """,
        (hotel_id, stay_date, as_of_datetime),
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from runtime.sales_progress.repository import DirectSalesProgressRepository

    DirectSalesProgressRepository.current_forecast = current_forecast
    DirectSalesProgressRepository._S15_S16_CURRENT_BATCH_PATCH_VERSION = VERSION
