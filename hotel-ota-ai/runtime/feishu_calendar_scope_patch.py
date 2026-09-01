from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import hashlib
import os
import re
from typing import Any


_INSTALLED = False
_INTENT = "calendar_season_tag_write"
_MANUAL_SEASON_TAGS = {"淡季", "平季", "旺季"}
_CURRENT_CHAT_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "hotel_ota_current_feishu_chat_id",
    default=None,
)
_DATE_TOKEN_RE = re.compile(
    r"20\d{2}(?:[-/.]\d{1,2}[-/.]\d{1,2}|年\d{1,2}月\d{1,2}日?)"
)
_MONTH_TOKEN_RE = re.compile(r"(20\d{2})年(\d{1,2})月")
_YEAR_TOKEN_RE = re.compile(r"(20\d{2})年?")
_CHANGE_TERMS = ("设置", "设为", "设成", "标记", "标为", "定为", "改为", "写入", "更新为")
_RESET_TERMS = (
    "恢复默认",
    "恢复为默认",
    "恢复系统默认",
    "恢复为系统默认",
    "恢复系统标签",
    "恢复为系统标签",
    "改回默认",
    "改回系统默认",
    "改回原来的标签",
    "恢复原来的标签",
    "清除人工标签",
    "取消人工标签",
    "撤销人工标签",
)
_QUERY_TERMS = ("什么时候", "哪些天", "哪天", "查询", "查看", "列出", "显示", "有没有", "是什么", "什么时间")
_QUERY_GENERIC_TERMS = ("淡旺季", "季节标签", "season_tag")
_LIST_SEPARATORS = ("和", "、", "以及", "及", "与", "，", ",")


def _normalize_date(value: str) -> dt.date:
    text = value.strip().replace("年", "-").replace("月", "-").replace("日", "")
    text = text.replace("/", "-").replace(".", "-")
    parts = text.split("-")
    if len(parts) != 3:
        raise ValueError("calendar_season_date_invalid")
    return dt.date(int(parts[0]), int(parts[1]), int(parts[2]))


def _daterange(start: dt.date, end: dt.date) -> list[dt.date]:
    if start > end:
        raise ValueError("calendar_season_date_range_reversed")
    if (end - start).days > 730:
        raise OverflowError("calendar_season_date_range_too_large")
    return [start + dt.timedelta(days=offset) for offset in range((end - start).days + 1)]


def _parse_date_scope(text: str, *, allow_missing: bool = False) -> dict[str, Any]:
    tokens = _DATE_TOKEN_RE.findall(text)
    try:
        if len(tokens) == 1:
            dates = [_normalize_date(tokens[0])]
            scope_kind = "single_date"
        elif len(tokens) >= 2:
            parsed = [_normalize_date(token) for token in tokens]
            is_discrete = any(separator in text for separator in _LIST_SEPARATORS)
            if is_discrete:
                dates = list(dict.fromkeys(parsed))
                if len(dates) > 731:
                    raise OverflowError("calendar_season_date_range_too_large")
                scope_kind = "date_list"
            elif len(parsed) == 2:
                dates = _daterange(parsed[0], parsed[1])
                scope_kind = "date_range"
            else:
                return {
                    "status": "blocked",
                    "reason": "calendar_season_date_range_not_unique",
                }
        else:
            month_match = _MONTH_TOKEN_RE.search(text)
            if month_match:
                year, month = int(month_match.group(1)), int(month_match.group(2))
                start = dt.date(year, month, 1)
                if month == 12:
                    end = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
                else:
                    end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
                dates = _daterange(start, end)
                scope_kind = "month"
            elif allow_missing:
                return {"status": "ok", "scope_kind": "unspecified", "target_dates": []}
            else:
                return {
                    "status": "blocked",
                    "reason": "calendar_season_exact_date_required",
                }
    except OverflowError:
        return {
            "status": "blocked",
            "reason": "calendar_season_date_range_too_large",
        }
    except (TypeError, ValueError) as exc:
        reason = str(exc)
        if reason not in {
            "calendar_season_date_invalid",
            "calendar_season_date_range_reversed",
        }:
            reason = "calendar_season_date_invalid"
        return {"status": "blocked", "reason": reason}

    if not dates:
        return {
            "status": "blocked",
            "reason": "calendar_season_exact_date_required",
        }
    ordered = sorted(dict.fromkeys(dates))
    return {
        "status": "ok",
        "scope_kind": scope_kind,
        "target_dates": [value.isoformat() for value in ordered],
        "start_date": ordered[0].isoformat(),
        "end_date": ordered[-1].isoformat(),
        "day_count": len(ordered),
    }


def parse_calendar_season_tag_command(message: str | None) -> dict[str, Any] | None:
    text = str(message or "").strip()
    reset_requested = any(term in text for term in _RESET_TERMS)
    tag = next((value for value in _MANUAL_SEASON_TAGS if value in text), None)

    if reset_requested:
        scope = _parse_date_scope(text)
        return {
            **scope,
            "operation": "reset",
            "season_tag": None,
        }
    if not tag or not any(term in text for term in _CHANGE_TERMS):
        return None

    scope = _parse_date_scope(text)
    return {
        **scope,
        "operation": "set",
        "season_tag": tag,
    }


def parse_calendar_season_tag_query(message: str | None) -> dict[str, Any] | None:
    text = str(message or "").strip()
    if not text or parse_calendar_season_tag_command(text) is not None:
        return None

    tag = next((value for value in _MANUAL_SEASON_TAGS if value in text), None)
    generic = any(term in text for term in _QUERY_GENERIC_TERMS)
    if not generic and not (tag and any(term in text for term in _QUERY_TERMS)):
        return None

    scope = _parse_date_scope(text, allow_missing=True)
    if scope.get("status") != "ok":
        return {**scope, "season_tag": tag}
    return {
        **scope,
        "season_tag": tag,
    }


def _chat_hash(chat_id: str) -> str:
    return hashlib.sha256(f"feishu-chat:{chat_id}".encode("utf-8")).hexdigest()


def _manual_tags_for_year(db_path: str, year: int) -> list[tuple[str, str]]:
    from runtime.storage import connect, init_schema

    with contextlib.closing(connect(db_path)) as conn:
        init_schema(conn)
        rows = conn.execute(
            """
            SELECT date, season_tag
            FROM calendar_days
            WHERE year=? AND season_tag IN ('淡季', '平季', '旺季')
            ORDER BY date
            """,
            (year,),
        ).fetchall()
    return [(str(row["date"]), str(row["season_tag"])) for row in rows]


def _restore_manual_tags(db_path: str, rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    from runtime.common import now_local
    from runtime.storage import connect, init_schema

    timestamp = now_local()
    with contextlib.closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            conn.executemany(
                "UPDATE calendar_days SET season_tag=?, updated_at=? WHERE date=?",
                [(tag, timestamp, date_value) for date_value, tag in rows],
            )


def _normalize_target_dates(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    target_dates: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[dt.date], str | None]:
    try:
        if target_dates:
            parsed = sorted({dt.date.fromisoformat(str(value)) for value in target_dates})
            if len(parsed) > 731:
                return [], "calendar_season_date_range_too_large"
            return parsed, None
        if not start_date or not end_date:
            return [], "calendar_season_exact_date_required"
        start = dt.date.fromisoformat(start_date)
        end = dt.date.fromisoformat(end_date)
        return _daterange(start, end), None
    except OverflowError:
        return [], "calendar_season_date_range_too_large"
    except (TypeError, ValueError) as exc:
        reason = str(exc)
        if reason == "calendar_season_date_range_reversed":
            return [], reason
        return [], "calendar_season_date_invalid"


def _ensure_calendar_years(db_path: str, dates: list[dt.date]) -> None:
    from runtime.decisions import calendar as calendar_module

    for year in sorted({value.year for value in dates}):
        calendar_module.sync_calendar_year(db_path, year)


def _read_tags_for_dates(db_path: str, dates: list[dt.date]) -> list[tuple[str, str]]:
    from runtime.storage import connect, init_schema

    if not dates:
        return []
    date_values = [value.isoformat() for value in dates]
    placeholders = ",".join("?" for _ in date_values)
    with contextlib.closing(connect(db_path)) as conn:
        init_schema(conn)
        rows = conn.execute(
            f"""
            SELECT date, season_tag
            FROM calendar_days
            WHERE date IN ({placeholders})
            ORDER BY date
            """,
            date_values,
        ).fetchall()
    return [(str(row["date"]), str(row["season_tag"])) for row in rows]


def set_calendar_season_tag(
    db_path: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    season_tag: str,
    target_dates: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if season_tag not in _MANUAL_SEASON_TAGS:
        return {"status": "blocked", "reason": "calendar_season_tag_invalid"}
    dates, error = _normalize_target_dates(
        start_date=start_date,
        end_date=end_date,
        target_dates=target_dates,
    )
    if error:
        return {"status": "blocked", "reason": error}
    if not dates:
        return {"status": "blocked", "reason": "calendar_season_exact_date_required"}

    from runtime.common import now_local
    from runtime.storage import connect, init_schema

    _ensure_calendar_years(db_path, dates)
    timestamp = now_local()
    with contextlib.closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            conn.executemany(
                "UPDATE calendar_days SET season_tag=?, updated_at=? WHERE date=?",
                [(season_tag, timestamp, value.isoformat()) for value in dates],
            )

    rows = _read_tags_for_dates(db_path, dates)
    expected_rows = len(dates)
    verified = len(rows) == expected_rows and all(tag == season_tag for _, tag in rows)
    return {
        "status": "ok" if verified else "error",
        "reason": None if verified else "calendar_season_write_readback_mismatch",
        "operation": "set",
        "season_tag": season_tag,
        "start_date": dates[0].isoformat(),
        "end_date": dates[-1].isoformat(),
        "target_dates": [value.isoformat() for value in dates],
        "updated_rows": len(rows),
        "expected_rows": expected_rows,
        "readback_verified": verified,
    }


def reset_calendar_season_tag(
    db_path: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    target_dates: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    dates, error = _normalize_target_dates(
        start_date=start_date,
        end_date=end_date,
        target_dates=target_dates,
    )
    if error:
        return {"status": "blocked", "reason": error}
    if not dates:
        return {"status": "blocked", "reason": "calendar_season_exact_date_required"}

    from runtime.common import now_local
    from runtime.decisions import calendar as calendar_module
    from runtime.storage import connect, init_schema

    _ensure_calendar_years(db_path, dates)
    defaults: dict[str, str] = {}
    selected = {value.isoformat() for value in dates}
    for year in sorted({value.year for value in dates}):
        for row in calendar_module.build_calendar_days(year):
            date_value = str(row.get("date") or "")
            if date_value in selected:
                defaults[date_value] = str(row.get("season_tag") or "")

    if len(defaults) != len(dates) or any(not value for value in defaults.values()):
        return {
            "status": "error",
            "reason": "calendar_season_default_resolution_failed",
            "operation": "reset",
        }

    timestamp = now_local()
    with contextlib.closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            conn.executemany(
                "UPDATE calendar_days SET season_tag=?, updated_at=? WHERE date=?",
                [
                    (defaults[value.isoformat()], timestamp, value.isoformat())
                    for value in dates
                ],
            )

    rows = _read_tags_for_dates(db_path, dates)
    verified = len(rows) == len(dates) and all(defaults.get(date_value) == tag for date_value, tag in rows)
    return {
        "status": "ok" if verified else "error",
        "reason": None if verified else "calendar_season_reset_readback_mismatch",
        "operation": "reset",
        "season_tag": None,
        "start_date": dates[0].isoformat(),
        "end_date": dates[-1].isoformat(),
        "target_dates": [value.isoformat() for value in dates],
        "restored_tags": [{"date": date_value, "season_tag": tag} for date_value, tag in rows],
        "updated_rows": len(rows),
        "expected_rows": len(dates),
        "readback_verified": verified,
    }


def _query_calendar_season_tags(
    db_path: str,
    *,
    season_tag: str | None,
    scope: dict[str, Any],
) -> dict[str, Any]:
    from runtime.common import today
    from runtime.decisions import calendar as calendar_module
    from runtime.storage import connect, init_schema

    target_dates = list(scope.get("target_dates") or [])
    if target_dates:
        parsed_dates, error = _normalize_target_dates(target_dates=target_dates)
        if error:
            return {"status": "blocked", "reason": error}
        dates = parsed_dates
        start = dates[0]
        end = dates[-1]
        discrete = scope.get("scope_kind") in {"single_date", "date_list"}
    else:
        year_match = _YEAR_TOKEN_RE.search(str(scope.get("query_text") or ""))
        year = int(year_match.group(1)) if year_match else dt.date.fromisoformat(today()).year
        start = dt.date(year, 1, 1)
        end = dt.date(year, 12, 31)
        dates = []
        discrete = False

    for year in range(start.year, end.year + 1):
        calendar_module.sync_calendar_year(db_path, year)

    with contextlib.closing(connect(db_path)) as conn:
        init_schema(conn)
        params: list[Any] = []
        clauses: list[str] = []
        if discrete:
            date_values = [value.isoformat() for value in dates]
            placeholders = ",".join("?" for _ in date_values)
            clauses.append(f"date IN ({placeholders})")
            params.extend(date_values)
        else:
            clauses.append("date>=? AND date<=?")
            params.extend([start.isoformat(), end.isoformat()])
        if season_tag:
            clauses.append("season_tag=?")
            params.append(season_tag)
        else:
            clauses.append("season_tag IN ('淡季', '平季', '旺季')")
        rows = conn.execute(
            f"""
            SELECT date, season_tag
            FROM calendar_days
            WHERE {' AND '.join(clauses)}
            ORDER BY date
            """,
            params,
        ).fetchall()

    matches = [{"date": str(row["date"]), "season_tag": str(row["season_tag"])} for row in rows]
    return {
        "status": "ok",
        "season_tag": season_tag,
        "season_tag_matches": matches,
        "match_count": len(matches),
        "query_start_date": start.isoformat(),
        "query_end_date": end.isoformat(),
    }


def _season_query_summary(result: dict[str, Any]) -> str:
    tag = result.get("season_tag")
    matches = list(result.get("season_tag_matches") or [])
    if tag:
        if not matches:
            return (
                f"{result.get('query_start_date')} 至 {result.get('query_end_date')} "
                f"没有人工标记为“{tag}”的日期。系统默认标签不会自动等同于人工“{tag}”。"
            )
        dates = "、".join(str(item.get("date")) for item in matches[:60])
        suffix = f"；另有 {len(matches) - 60} 天未展开" if len(matches) > 60 else ""
        return (
            f"人工 season_tag=“{tag}”共 {len(matches)} 天：{dates}{suffix}。"
            "每个日期只有一个 season_tag；人工标签是覆盖值，不与系统默认标签叠加。"
        )
    if not matches:
        return (
            f"{result.get('query_start_date')} 至 {result.get('query_end_date')} "
            "没有人工淡季/平季/旺季标签。"
        )
    items = "、".join(f"{item.get('date')}={item.get('season_tag')}" for item in matches[:60])
    suffix = f"；另有 {len(matches) - 60} 天未展开" if len(matches) > 60 else ""
    return f"人工淡旺季标签共 {len(matches)} 天：{items}{suffix}。"


def _apply_rendered_summary(router: Any, result: dict[str, Any], *, role: str, text: str) -> None:
    from runtime.safety.feishu_output import feishu_output_gate

    rendered = router.render_feishu_output(result, result.get("output_profile"))
    send_payload = router.build_feishu_send_payload(result, role=role)
    delivery_gate = feishu_output_gate(source="feishu", content_kind="text", message=text)
    if delivery_gate.get("status") != "ok":
        text = "您好，该内容不能通过飞书业务通道发送。"
    if isinstance(rendered, dict):
        rendered = dict(rendered)
        rendered["text"] = text
    if isinstance(send_payload, dict):
        send_payload = dict(send_payload)
        warnings = list(send_payload.get("warnings") or [])
        if delivery_gate.get("status") != "ok":
            warnings.append(f"feishu_output_gate:{delivery_gate.get('blocked_reason')}")
            send_payload["send_allowed"] = False
        send_payload["warnings"] = warnings
        send_payload["text"] = text
    result["rendered"] = rendered
    result["send_payload"] = send_payload


def _route_season_query(
    router: Any,
    previous_route: Any,
    message: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    query = parse_calendar_season_tag_query(message) or {
        "status": "blocked",
        "reason": "calendar_season_query_invalid",
    }
    base_kwargs = dict(kwargs)
    render_requested = bool(base_kwargs.pop("render", False))
    result = previous_route("业务日历", render=False, **base_kwargs)
    if result.get("status") == "blocked":
        if render_requested:
            role = str(result.get("auth_role") or kwargs.get("role") or "guest")
            result["rendered"] = router.render_feishu_output(result, result.get("output_profile"))
            result["send_payload"] = router.build_feishu_send_payload(result, role=role)
        return result

    db_path = kwargs.get("db_path") or os.environ.get("HOTEL_OTA_DB")
    if query.get("status") != "ok":
        result.update(query)
        result["status"] = "blocked"
        result["blocked_reason"] = query.get("reason")
    elif not db_path:
        result.update(
            {
                "status": "data_gap",
                "blocked_reason": "calendar_season_sqlite_path_missing",
            }
        )
    else:
        query_payload = dict(query)
        query_payload["query_text"] = message
        result.update(
            _query_calendar_season_tags(
                str(db_path),
                season_tag=query.get("season_tag"),
                scope=query_payload,
            )
        )
        result.update(
            {
                "intent": "business_calendar",
                "runtime_command": "calendar-season-tag-query",
                "season_tag_query": True,
                "business_result_generated": True,
            }
        )
        result["summary"] = _season_query_summary(result)

    if render_requested:
        role = str(result.get("auth_role") or kwargs.get("role") or "guest")
        text = result.get("summary") or "淡旺季标签查询未完成。"
        _apply_rendered_summary(router, result, role=role, text=str(text))
    return result


def _scoped_named_role_target(
    db_path: str | None,
    *,
    hotel_id: str | None,
    target: str,
    member_info: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from runtime.common import now_local
    from runtime.safety.auth import normalize_feishu_chat_id
    from runtime.storage import connect, init_schema

    target_text = str(target or "").strip()
    chat_id = normalize_feishu_chat_id(_CURRENT_CHAT_ID.get())
    if not db_path or not hotel_id or not target_text:
        return {"status": "blocked", "reason": "role_membership_target_not_found"}
    if not chat_id:
        return {"status": "blocked", "reason": "role_membership_current_chat_required"}
    if target_text in {"群里的一个人", "群里一个人", "某个人", "某某", "那个人", "一个人"}:
        return {"status": "blocked", "reason": "role_membership_target_not_found"}

    chat_id_hash = _chat_hash(chat_id)
    try:
        with contextlib.closing(connect(db_path)) as conn:
            init_schema(conn)
            candidates = conn.execute(
                """
                SELECT DISTINCT p.principal_id
                FROM auth_principals p
                JOIN chat_role_memberships cm ON cm.principal_id=p.principal_id
                WHERE cm.hotel_id=? AND cm.chat_id_hash=?
                  AND cm.status='active' AND p.status='active'
                  AND (
                    p.principal_id=? OR p.display_name=? OR p.alias=? OR p.name_snapshot=?
                  )
                """,
                (hotel_id, chat_id_hash, target_text, target_text, target_text, target_text),
            ).fetchall()
    except Exception:
        return {"status": "blocked", "reason": "role_membership_target_not_found"}

    if len(candidates) == 1:
        return {
            "status": "ok",
            "principal_id": str(candidates[0]["principal_id"]),
            "source": "current_chat_membership",
        }
    if len(candidates) > 1:
        return {"status": "blocked", "reason": "role_membership_target_not_unique_in_current_chat"}

    matches: list[dict[str, Any]] = []
    for item in member_info or []:
        names = {
            str(item.get("name") or "").strip(),
            str(item.get("display_name") or "").strip(),
            str(item.get("nickname") or "").strip(),
        }
        if target_text in names:
            matches.append(item)
    if len(matches) != 1:
        return {
            "status": "blocked",
            "reason": "member_info_match_not_unique" if matches else "role_membership_target_not_found",
        }

    identity = matches[0]
    open_id = str(identity.get("open_id") or "").strip() or None
    user_id = str(identity.get("user_id") or "").strip() or None
    union_id = str(identity.get("union_id") or "").strip() or None
    identity_value = open_id or user_id or union_id
    if not identity_value:
        return {"status": "blocked", "reason": "member_info_identity_missing"}

    principal_id = f"feishu:{hashlib.sha256(identity_value.encode('utf-8')).hexdigest()[:12]}"
    timestamp = now_local()
    try:
        with contextlib.closing(connect(db_path)) as conn:
            with conn:
                init_schema(conn)
                existing = conn.execute(
                    """
                    SELECT principal_id
                    FROM auth_principals
                    WHERE (open_id=? OR user_id=? OR union_id=?)
                    LIMIT 1
                    """,
                    (open_id, user_id, union_id),
                ).fetchone()
                if existing:
                    principal_id = str(existing["principal_id"])
                else:
                    conn.execute(
                        """
                        INSERT INTO auth_principals (
                          principal_id, open_id, user_id, union_id, display_name,
                          status, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, 'candidate', ?, ?)
                        """,
                        (principal_id, open_id, user_id, union_id, target_text, timestamp, timestamp),
                    )
    except Exception:
        return {"status": "blocked", "reason": "member_info_candidate_persist_failed"}
    return {
        "status": "ok",
        "principal_id": principal_id,
        "source": "current_chat_member_info",
    }


def _route_season_tag(router: Any, message: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    payload = parse_calendar_season_tag_command(message) or {
        "status": "blocked",
        "reason": "calendar_season_command_invalid",
    }
    role = str(kwargs.get("role") or "guest")
    output_profile = kwargs.get("output_profile")
    result = router._base_result(_INTENT, role=role, output_profile=output_profile)
    result.update(payload)
    operation = str(payload.get("operation") or "set")
    result.update(
        {
            "intent": _INTENT,
            "runtime_command": (
                "calendar-season-tag-reset"
                if operation == "reset"
                else "calendar-season-tag-write"
            ),
            "config_change_applied": False,
            "sqlite_written": False,
            "formal_approval_created": False,
            "live_execution_count": 0,
        }
    )

    chat_id = kwargs.get("chat_id")
    chat_type = str(kwargs.get("chat_type") or "group")
    db_path = kwargs.get("db_path")
    auth_context = router.build_auth_context(
        source="feishu",
        user_id=kwargs.get("user_id"),
        open_id=kwargs.get("open_id"),
        union_id=kwargs.get("union_id"),
        chat_id=chat_id,
        chat_type=chat_type,
        user_role=role,
        config_path=kwargs.get("auth_config"),
        auth_db_path=db_path,
        requested_hotel_id=kwargs.get("hotel_id"),
    )
    resolved_role = str(auth_context.get("user_role") or "guest")
    resolved_hotel_id = auth_context.get("resolved_hotel_id")
    result.update(
        {
            "auth_role": resolved_role,
            "personal_role": resolved_role,
            "auth_backend": auth_context.get("auth_backend"),
            "auth_status": auth_context.get("auth_status"),
            "tenant_status": auth_context.get("tenant_status"),
            "hotel_id": resolved_hotel_id,
            "resolved_hotel_id": resolved_hotel_id,
        }
    )

    if payload.get("status") != "ok":
        pass
    elif chat_type not in {"group", "chat"}:
        result.update({"status": "blocked", "reason": "calendar_season_group_chat_required"})
    elif auth_context.get("auth_status") != "authorized" or not resolved_hotel_id:
        result.update(
            {
                "status": "blocked",
                "reason": auth_context.get("reason") or "calendar_season_auth_required",
            }
        )
    elif resolved_role not in {"admin", "owner"}:
        result.update({"status": "blocked", "reason": "calendar_season_write_permission_denied"})
    elif not db_path:
        result.update({"status": "blocked", "reason": "calendar_season_sqlite_path_missing"})
    else:
        if operation == "reset":
            write_result = reset_calendar_season_tag(
                str(db_path),
                target_dates=list(payload.get("target_dates") or []),
            )
        else:
            write_result = set_calendar_season_tag(
                str(db_path),
                target_dates=list(payload.get("target_dates") or []),
                season_tag=str(payload["season_tag"]),
            )
        result.update(write_result)
        applied = write_result.get("status") == "ok" and bool(write_result.get("readback_verified"))
        result["config_change_applied"] = applied
        result["sqlite_written"] = applied

    if result.get("status") == "ok":
        target_dates = list(result.get("target_dates") or [])
        target_text = "、".join(target_dates[:20])
        if len(target_dates) > 20:
            target_text += f" 等 {len(target_dates)} 天"
        if operation == "reset":
            restored = list(result.get("restored_tags") or [])
            restored_text = "、".join(
                f"{item.get('date')}={item.get('season_tag')}" for item in restored[:20]
            )
            if len(restored) > 20:
                restored_text += f" 等 {len(restored)} 天"
            result["summary"] = (
                f"已将 {target_text} 的人工淡旺季覆盖撤销，"
                f"season_tag 恢复为系统日历算法默认值：{restored_text}。"
            )
        else:
            result["summary"] = (
                f"已将 {target_text} 的 calendar_days.season_tag 标记为"
                f"{result.get('season_tag')}，共 {result.get('updated_rows')} 天。"
            )
    else:
        if operation == "reset" and result.get("reason") == "calendar_season_exact_date_required":
            result["summary"] = (
                "恢复默认需要明确日期，不能由 deterministic runtime 猜“这俩天”。"
                "请使用例如：将2026-08-07和2026-08-09恢复为系统默认。"
            )
        else:
            result["summary"] = (
                "淡旺季标签未写入。设置示例：将2026-08-01至2026-08-31设为旺季；"
                "恢复示例：将2026-08-07和2026-08-09恢复为系统默认。"
            )
        result["blocked_reason"] = result.get("reason")

    if kwargs.get("render"):
        _apply_rendered_summary(
            router,
            result,
            role=resolved_role,
            text=str(result.get("summary") or ""),
        )
    return result


def _install_calendar_sync_patch() -> None:
    from runtime.decisions import calendar as calendar_module

    previous = calendar_module.sync_calendar_year

    def sync_calendar_year_preserving_manual_tags(
        db_path: str,
        year: int,
        seed_file: str | None = None,
    ) -> dict[str, Any]:
        preserved = _manual_tags_for_year(db_path, year)
        result = previous(db_path, year, seed_file)
        _restore_manual_tags(db_path, preserved)
        if isinstance(result, dict):
            result = dict(result)
            result["manual_season_tags_preserved"] = len(preserved)
        return result

    sync_calendar_year_preserving_manual_tags.__name__ = previous.__name__
    sync_calendar_year_preserving_manual_tags.__doc__ = previous.__doc__
    calendar_module.sync_calendar_year = sync_calendar_year_preserving_manual_tags


def _install_router_patch() -> None:
    from runtime import feishu_command_router as router

    previous_detect = router._detect_intent
    previous_permission_action = router._permission_action_for_intent
    previous_route = router.route_feishu_command

    def detect_intent(message: str) -> str:
        if parse_calendar_season_tag_command(message) is not None:
            return _INTENT
        if parse_calendar_season_tag_query(message) is not None:
            return "business_calendar"
        return previous_detect(message)

    def permission_action_for_intent(intent: str) -> str:
        if intent == _INTENT:
            return "confirm_configuration_change"
        return previous_permission_action(intent)

    def route_feishu_command_with_chat_scope(message: str, **kwargs: Any) -> dict[str, Any]:
        token = _CURRENT_CHAT_ID.set(kwargs.get("chat_id"))
        try:
            if parse_calendar_season_tag_command(message) is not None:
                return _route_season_tag(router, message, kwargs)
            if parse_calendar_season_tag_query(message) is not None:
                return _route_season_query(router, previous_route, message, kwargs)
            return previous_route(message, **kwargs)
        finally:
            _CURRENT_CHAT_ID.reset(token)

    router._detect_intent = detect_intent
    router._permission_action_for_intent = permission_action_for_intent
    router._resolve_named_role_target = _scoped_named_role_target
    router.route_feishu_command = route_feishu_command_with_chat_scope
    router.PROTECTED_BUSINESS_INTENTS.add(_INTENT)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    _install_calendar_sync_patch()
    _install_router_patch()
