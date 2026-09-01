from __future__ import annotations

import datetime as dt
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Mapping, Sequence

from runtime.s12_reputation_real import (
    DETAIL_TABLES,
    PLATFORM_LABELS,
    SHANGHAI_TZ,
    S12DataGap,
    S12MySQLSource,
    _latest,
    _row_platform,
    _safe_identifier,
)


CHANNEL_FAMILIES = {
    "meituan": "meituan",
    "dianping": "meituan",
    "ctrip": "ctrip",
    "qunar": "ctrip",
    "tongcheng": "ctrip",
    "zhixing": "ctrip",
}
PLATFORM_ORDER = ("meituan", "dianping", "ctrip", "qunar", "tongcheng", "zhixing")
POSITIVE_REVIEW_SCORE = 4.0
LOW_REVIEW_SCORE = 3.0
_CHANNEL_SCOPE_CACHE_TTL_SECONDS = 300
_CHANNEL_SCOPE_CACHE: dict[tuple[str, int, str, str], tuple[float, set[str] | None, bool]] = {}
_CHANNEL_SCOPE_LOCK = Lock()


def _local(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=SHANGHAI_TZ) if value.tzinfo is None else value.astimezone(SHANGHAI_TZ)


def _day_bounds(as_of: dt.datetime, days: int) -> tuple[dt.datetime, dt.datetime]:
    if days not in {1, 2, 3}:
        raise ValueError("days must be 1, 2, or 3")
    local = _local(as_of)
    end = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return end - dt.timedelta(days=days), end


def _review_day(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return _local(value).date().isoformat()
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else None


def _channel_name(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    aliases = {
        "美团": "meituan",
        "点评": "meituan",
        "大众点评": "meituan",
        "meituan": "meituan",
        "mt": "meituan",
        "携程": "ctrip",
        "去哪儿": "ctrip",
        "同程": "ctrip",
        "智行": "ctrip",
        "ctrip": "ctrip",
    }
    return aliases.get(text)


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "replied", "已回复", "negative", "差评"}:
        return True
    if text in {"0", "false", "no", "n", "unreplied", "未回复", "normal", "非差评"}:
        return False
    return None


def _enabled_channels(source: S12MySQLSource, hotel_id: str) -> tuple[set[str] | None, bool]:
    """Read the hotel channel scope; unavailable configuration fails open."""
    source_kwargs = getattr(source, "_kwargs", {})
    key = (
        str(source_kwargs.get("host") or ""),
        int(source_kwargs.get("port") or 3306),
        str(source_kwargs.get("database") or ""),
        hotel_id,
    )
    now = time.monotonic()
    with _CHANNEL_SCOPE_LOCK:
        cached = _CHANNEL_SCOPE_CACHE.get(key)
    if cached and now - cached[0] < _CHANNEL_SCOPE_CACHE_TTL_SECONDS:
        return cached[1], cached[2]
    try:
        columns = source._columns("hotels")
        if "hotel_id" not in columns or "config_json" not in columns:
            return None, False
        rows = source._query(
            "SELECT `config_json` FROM `hotels` WHERE `hotel_id`=%s",
            (hotel_id,),
        )
        if not rows or rows[0].get("config_json") in (None, ""):
            return None, False
        raw = rows[0]["config_json"]
        config = json.loads(raw) if isinstance(raw, str) else raw
        values = config.get("channels") or config.get("enabled_channels") if isinstance(config, Mapping) else None
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            return None, False
        channels = {channel for value in values if (channel := _channel_name(value))}
        result = (channels or None, True)
    except (S12DataGap, TypeError, ValueError, json.JSONDecodeError):
        result = (None, False)
    with _CHANNEL_SCOPE_LOCK:
        _CHANNEL_SCOPE_CACHE[key] = (now, *result)
    return result


def _daily_detail_rows(
    source: S12MySQLSource,
    table: str,
    *,
    hotel_id: str,
    start: dt.datetime,
    end: dt.datetime,
    as_of: dt.datetime,
    default_platform: str,
) -> tuple[list[dict[str, Any]], int]:
    columns = source._columns(table)
    required = {"hotel_id", "review_id", "review_time", "snapshot_time"}
    missing = sorted(required - columns)
    if missing:
        raise S12DataGap(f"{table}:missing_columns:{','.join(missing)}")
    wanted = {
        "id", "hotel_id", "review_id", "review_time", "snapshot_time",
        "channel_source", "review_platform", "platform_scope", "source_platform",
        "is_replied", "merchant_reply_time", "merchant_reply_content",
        "review_score", "star_rating", "is_negative_review",
    }
    selected = sorted(columns & wanted)
    rows = source._query(
        f"SELECT {', '.join(f'`{_safe_identifier(name)}`' for name in selected)} "
        f"FROM `{_safe_identifier(table)}` "
        "WHERE `hotel_id`=%s AND `review_time`>=%s AND `review_time`<%s AND `snapshot_time`<=%s",
        (hotel_id, start.replace(tzinfo=None), end.replace(tzinfo=None), as_of.replace(tzinfo=None)),
    )
    for row in rows:
        row["platform"] = _row_platform(row, default_platform)
    return _latest(rows, grain=("hotel_id", "platform", "review_id"))


def _quality_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reply_values = [_reply_state(row) for row in rows]
    known_reply = [value for value in reply_values if value is not None]
    scores = [
        value
        for row in rows
        if (value := _number(row.get("review_score", row.get("star_rating")))) is not None
    ]
    negative_values = [_flag(row.get("is_negative_review")) for row in rows]
    known_negative = [value for value in negative_values if value is not None]

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    replied_count = sum(value is True for value in known_reply)
    positive_count = sum(value >= POSITIVE_REVIEW_SCORE for value in scores)
    low_score_count = sum(value <= LOW_REVIEW_SCORE for value in scores)
    negative_count = sum(value is True for value in known_negative)
    return {
        "row_count": len(rows),
        "current_reply": {
            "known_count": len(known_reply),
            "replied_count": replied_count,
            "unreplied_count": sum(value is False for value in known_reply),
            "rate": ratio(replied_count, len(known_reply)),
        },
        "rating": {
            "known_count": len(scores),
            "positive_count": positive_count,
            "positive_rate": ratio(positive_count, len(scores)),
            "low_score_count": low_score_count,
            "low_score_rate": ratio(low_score_count, len(scores)),
        },
        "source_negative": {
            "known_count": len(known_negative),
            "count": negative_count,
            "rate": ratio(negative_count, len(known_negative)),
        },
    }


def _reply_state(row: Mapping[str, Any]) -> bool | None:
    """Prefer the explicit reply flag; use merchant facts only when it is absent."""
    if (value := _flag(row.get("is_replied"))) is not None:
        return value
    return True if any(str(row.get(key) or "").strip() for key in (
        "merchant_reply_time", "merchant_reply_content",
    )) else None


def build_s12_daily_new_reviews_report(
    *,
    hotel_id: str,
    as_of: dt.datetime,
    source: S12MySQLSource,
    days: int = 1,
) -> dict[str, Any]:
    as_of_local = _local(as_of)
    start, end = _day_bounds(as_of_local, days)
    enabled_channels, channel_config_available = _enabled_channels(source, hotel_id)
    rows_by_platform: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    data_gaps: list[str] = []
    duplicates = 0
    queried_families = 0

    table_jobs = []
    for family, table, default_platform in DETAIL_TABLES:
        family_channel = CHANNEL_FAMILIES.get(default_platform)
        if enabled_channels is not None and family_channel not in enabled_channels:
            continue
        table_jobs.append((family, table, default_platform))

    with ThreadPoolExecutor(max_workers=max(1, len(table_jobs))) as executor:
        futures = {
            (family, default_platform): executor.submit(
                _daily_detail_rows,
                source,
                table,
                hotel_id=hotel_id,
                start=start,
                end=end,
                as_of=as_of_local,
                default_platform=default_platform,
            )
            for family, table, default_platform in table_jobs
        }
        for family, _table, default_platform in table_jobs:
            try:
                rows, table_duplicates = futures[(family, default_platform)].result()
            except S12DataGap as exc:
                data_gaps.append(f"{family}:detail:{exc}")
                continue
            queried_families += 1
            duplicates += table_duplicates
            for row in rows:
                rows_by_platform[str(row.get("platform") or default_platform)].append(row)

    platform_counts: dict[str, int] = {}
    platform_quality: dict[str, dict[str, Any]] = {}
    all_rows: list[dict[str, Any]] = []
    for platform, rows in rows_by_platform.items():
        unique_rows, same_platform_duplicates = _latest(
            rows,
            grain=("hotel_id", "platform", "review_id"),
        )
        duplicates += same_platform_duplicates
        platform_counts[platform] = len(unique_rows)
        platform_quality[platform] = _quality_summary(unique_rows)
        all_rows.extend(unique_rows)

    total_rows, total_duplicates = _latest(
        all_rows,
        grain=("hotel_id", "platform", "review_id"),
    )
    duplicates += total_duplicates
    daily_counts = {
        (start + dt.timedelta(days=offset)).date().isoformat(): 0
        for offset in range(days)
    }
    for row in total_rows:
        if review_day := _review_day(row.get("review_time")):
            if review_day in daily_counts:
                daily_counts[review_day] += 1

    status = "ok" if queried_families and not data_gaps else "partial" if queried_families else "data_gap"
    quality_flags = [] if channel_config_available else ["ota_channel_config_unavailable"]
    return {
        "status": status,
        "skill_id": "S12",
        "intent": "reputation_daily_new_reviews",
        "hotel_id": hotel_id,
        "window_days": days,
        "target_review_date": start.date().isoformat(),
        "target_review_end_date": (end - dt.timedelta(days=1)).date().isoformat(),
        "window_start": start.isoformat(timespec="seconds"),
        "window_end": end.isoformat(timespec="seconds"),
        "daily_counts": daily_counts,
        "as_of_datetime": as_of_local.isoformat(timespec="seconds"),
        "platform_counts": {key: platform_counts[key] for key in PLATFORM_ORDER if key in platform_counts},
        "total_new_review_count": sum(platform_counts.values()),
        "quality_summary": _quality_summary(total_rows),
        "platform_quality_summary": {
            key: platform_quality[key]
            for key in PLATFORM_ORDER
            if key in platform_quality
        },
        "enabled_channels": sorted(enabled_channels) if enabled_channels else None,
        "data_gaps": sorted(set(data_gaps)),
        "quality_flags": quality_flags,
        "source_duplicate_count": duplicates,
        "data_source_type": "real_database" if queried_families else "unavailable",
        "business_result_generated": bool(queried_families),
        "approval_data_allowed": False,
        "live_allowed": False,
    }


def render_s12_daily_new_reviews_report(report: Mapping[str, Any]) -> str:
    days = int(report.get("window_days") or 1)
    title = "昨日新增评论" if days == 1 else f"近 {days} 天新增评论"
    if report.get("status") == "data_gap":
        return f"S12 {title}｜当前没有可用的真实评论明细，暂无法统计。"
    lines = [
        f"S12 {title}（真实数据只读）",
        f"统计区间：{report.get('target_review_date') or '—'} 至 "
        f"{report.get('target_review_end_date') or '—'}"
        "（按评论发布时间统计，每日 00:00:00 至次日 00:00:00）。",
        f"新增评论：{report.get('total_new_review_count', 0)} 条。",
    ]
    daily_counts = report.get("daily_counts") or {}
    if days > 1 and daily_counts:
        lines.append("按日新增：" + "｜".join(f"{day} {count} 条" for day, count in daily_counts.items()))
    counts = report.get("platform_counts") or {}
    if counts:
        lines.append("分平台：" + "｜".join(
            f"{PLATFORM_LABELS.get(platform, platform)} {count} 条"
            for platform, count in counts.items()
        ))
    else:
        lines.append("分平台：已查询的启用平台均为 0 条。")
    lines.extend(_render_quality("总计", report.get("quality_summary") or {}))
    platform_quality = report.get("platform_quality_summary") or {}
    if platform_quality:
        lines.append("分平台处理与质量：")
        for platform in PLATFORM_ORDER:
            if platform in platform_quality:
                lines.extend(_render_quality(
                    PLATFORM_LABELS.get(platform, platform),
                    platform_quality[platform],
                ))
    if "ota_channel_config_unavailable" in set(report.get("quality_flags") or []):
        lines.append("数据说明：未读取到渠道开关，已按可用评论来源展示。")
    if report.get("data_gaps"):
        lines.append("数据边界：部分评论来源不可用，未将缺失来源按 0 条处理。")
    return "\n".join(lines)


def _render_quality(label: str, summary: Mapping[str, Any]) -> list[str]:
    reply = summary.get("current_reply") or {}
    rating = summary.get("rating") or {}
    negative = summary.get("source_negative") or {}
    lines: list[str] = []
    if not summary.get("row_count"):
        return [f"{label}处理与质量：统计区间内无新增评论，回复率和好评率不计算。"]
    if reply.get("known_count"):
        lines.append(
            f"{label}回复率（统计区间内评论，截至当前）：已回复 {reply.get('replied_count', 0)} 条，"
            f"未回复 {reply.get('unreplied_count', 0)} 条，"
            f"回复率 {_pct(reply.get('rate'))}"
            f"（已识别 {reply.get('known_count')} 条）。"
        )
    else:
        lines.append(f"{label}回复率（统计区间内评论）：回复状态缺失，暂不计算。")
    if rating.get("known_count"):
        lines.append(
            f"{label}评价质量：好评（≥4分） {rating.get('positive_count', 0)} 条，"
            f"好评率 {_pct(rating.get('positive_rate'))}；"
            f"低分（≤3分） {rating.get('low_score_count', 0)} 条，"
            f"低分率 {_pct(rating.get('low_score_rate'))}"
            f"（已识别 {rating.get('known_count')} 条）。"
        )
    else:
        lines.append(f"{label}好评率：评分缺失，暂不计算。")
    if negative.get("known_count"):
        lines.append(
            f"{label}来源差评：{negative.get('count', 0)} 条，"
            f"占比 {_pct(negative.get('rate'))}"
            f"（已识别 {negative.get('known_count')} 条）。"
        )
    else:
        lines.append(f"{label}来源差评：来源差评标记缺失，暂不统计。")
    return lines


def _pct(value: Any) -> str:
    number = _number(value)
    return "—" if number is None else f"{number * 100:.1f}%"
