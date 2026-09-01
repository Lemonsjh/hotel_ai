from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any


_COLON_TIME = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*[:：]\s*([0-5]\d)(?!\d)")
_HOUR_TIME = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*点(?:钟)?(?!\d)")
_ISO_DATE = re.compile(r"(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)")
_CHINESE_MONTH_DAY = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?")


def normalize_as_of_time(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    match = _COLON_TIME.search(text)
    if match:
        return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
    match = _HOUR_TIME.search(text)
    if match:
        return f"{int(match.group(1)):02d}:00"
    return None


def minute_of_day(value: Any) -> int | None:
    normalized = normalize_as_of_time(value)
    if normalized is None:
        return None
    hour, minute = normalized.split(":", 1)
    return int(hour) * 60 + int(minute)


def _parse_explicit_date(message: str | None, now: datetime) -> tuple[str | None, str | None]:
    text = str(message or "")
    if "昨天" in text:
        return (now - timedelta(days=1)).date().isoformat(), "message_explicit"
    if "今天" in text or "今日" in text:
        return now.date().isoformat(), "message_explicit"
    match = _ISO_DATE.search(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day).date().isoformat(), "message_explicit"
        except ValueError:
            return None, None
    match = _CHINESE_MONTH_DAY.search(text)
    if match:
        month, day = (int(part) for part in match.groups())
        try:
            return datetime(now.year, month, day).date().isoformat(), "message_explicit"
        except ValueError:
            return None, None
    return None, None


def _parse_full_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _combine_date_time(date_text: str, time_text: str) -> str:
    return f"{date_text} {time_text}:00"


def resolve_request_as_of_time(
    message: str | None,
    *,
    explicit_as_of_time: str | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    request_now = now or datetime.now()
    explicit_datetime = _parse_full_datetime(explicit_as_of_time)
    if explicit_datetime is not None:
        return {
            "target_business_date": explicit_datetime.date().isoformat(),
            "as_of_time": explicit_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            "as_of_time_source": "explicit_argument",
        }
    explicit = normalize_as_of_time(explicit_as_of_time)
    if explicit is not None:
        business_date = request_now.date().isoformat()
        return {
            "target_business_date": business_date,
            "as_of_time": _combine_date_time(business_date, explicit),
            "as_of_time_source": "explicit_argument",
        }
    explicit_date, date_source = _parse_explicit_date(message, request_now)
    from_message = normalize_as_of_time(message)
    business_date = explicit_date or request_now.date().isoformat()
    if from_message is not None:
        return {
            "target_business_date": business_date,
            "as_of_time": _combine_date_time(business_date, from_message),
            "as_of_time_source": "message_explicit",
        }
    if explicit_date is not None:
        return {
            "target_business_date": explicit_date,
            "as_of_time": _combine_date_time(explicit_date, request_now.strftime("%H:%M")),
            "as_of_time_source": date_source or "message_explicit",
        }
    return {
        "target_business_date": business_date,
        "as_of_time": request_now.strftime("%Y-%m-%d %H:%M:%S"),
        "as_of_time_source": "request_clock",
    }
