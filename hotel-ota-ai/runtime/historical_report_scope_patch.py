from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import sys
from typing import Any, Callable, Mapping

VERSION = "historical-report-date-scope.v1"
SHANGHAI_TZ = timezone(timedelta(hours=8))
_INSTALLED_PRE = False
_INSTALLED_POST = False

_REPORT_TERMS = (
    "经营日报",
    "运营日报",
    "经营报告",
    "运营报告",
)
_ISO_DATE = re.compile(r"(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)")
_CHINESE_MONTH_DAY = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?")


def _now_shanghai(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI_TZ)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI_TZ)
    return current.astimezone(SHANGHAI_TZ)


def _message_report_date(message: str, *, now: datetime | None = None) -> str | None:
    text = str(message or "")
    current = _now_shanghai(now)
    if "昨天" in text or "昨日" in text:
        return (current - timedelta(days=1)).date().isoformat()
    match = _ISO_DATE.search(text)
    if match:
        year, month, day = (int(value) for value in match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None
    match = _CHINESE_MONTH_DAY.search(text)
    if match:
        month, day = (int(value) for value in match.groups())
        try:
            return datetime(current.year, month, day).date().isoformat()
        except ValueError:
            return None
    return None


def is_historical_operation_report(
    message: str | None,
    *,
    now: datetime | None = None,
) -> bool:
    text = str(message or "")
    if any(term in text.lower() for term in ("demo", "s14-ext")) or "演示" in text:
        return False
    if not any(term in text for term in _REPORT_TERMS):
        return False
    target = _message_report_date(text, now=now)
    return bool(target and target < _now_shanghai(now).date().isoformat())


def _normalise_relative_date_terms(message: str | None) -> str:
    return str(message or "").replace("昨日", "昨天")


def _wrap_time_resolver(previous: Callable[..., dict[str, str]]) -> Callable[..., dict[str, str]]:
    def resolve_request_as_of_time(
        message: str | None,
        *,
        explicit_as_of_time: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, str]:
        normalized_message = _normalise_relative_date_terms(message)
        result = dict(
            previous(
                normalized_message,
                explicit_as_of_time=explicit_as_of_time,
                now=now,
            )
        )
        if not is_historical_operation_report(message, now=now):
            return result

        # A historical daily report without an explicit cut-off means the
        # completed business day. Explicit message/API times still win.
        from runtime.time_context import normalize_as_of_time

        explicit_message_time = normalize_as_of_time(message)
        if explicit_as_of_time not in (None, "") or explicit_message_time is not None:
            return result
        target_date = str(result.get("target_business_date") or "")[:10]
        if target_date:
            result["as_of_time"] = f"{target_date} 23:59:59"
            result["as_of_time_source"] = "historical_report_day_close"
        return result

    resolve_request_as_of_time._HISTORICAL_REPORT_DATE_SCOPE_V1 = True  # type: ignore[attr-defined]
    return resolve_request_as_of_time


def parse_s14_request_as_of(value: Any, *, now: datetime | None = None) -> datetime:
    current = _now_shanghai(now)
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return current
        normalized = f"{text[:-1]}+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            try:
                hour, minute = text.split(":", 1)
                return current.replace(
                    hour=int(hour),
                    minute=int(minute),
                    second=0,
                    microsecond=0,
                )
            except (TypeError, ValueError):
                return current
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def _wrap_s14_message_detector(previous: Callable[[str], bool]) -> Callable[[str], bool]:
    def is_s14_operation_message(message: str) -> bool:
        return is_historical_operation_report(message) or previous(message)

    is_s14_operation_message._HISTORICAL_REPORT_DATE_SCOPE_V1 = True  # type: ignore[attr-defined]
    return is_s14_operation_message


def _wrap_router_detector(previous: Callable[[str], str]) -> Callable[[str], str]:
    def detect_intent(message: str) -> str:
        if is_historical_operation_report(message):
            return "operation_diagnosis"
        return previous(message)

    detect_intent._HISTORICAL_REPORT_DATE_SCOPE_V1 = True  # type: ignore[attr-defined]
    return detect_intent


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        normalized = f"{text[:-1]}+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def _wrap_market_proxy(previous: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def build_meituan_market_proxy(
        repository: Any,
        *,
        hotel_id: str,
        target_date: str,
        as_of_datetime: str,
        baseline_market_orders: Any,
        baseline_market_share: Any,
    ) -> dict[str, Any]:
        target_business_date = str(target_date or "")[:10]
        parsed_as_of = _parse_datetime(as_of_datetime)
        as_of_business_date = (
            parsed_as_of.date().isoformat() if parsed_as_of is not None else None
        )
        if (
            not target_business_date
            or as_of_business_date is None
            or as_of_business_date != target_business_date
        ):
            return {
                "status": "unavailable",
                "platform": "meituan",
                "reason": "target_as_of_business_date_mismatch",
                "target_business_date": target_business_date or None,
                "as_of_business_date": as_of_business_date,
                "cross_business_date_fallback_allowed": False,
            }
        result = dict(
            previous(
                repository,
                hotel_id=hotel_id,
                target_date=target_business_date,
                as_of_datetime=as_of_datetime,
                baseline_market_orders=baseline_market_orders,
                baseline_market_share=baseline_market_share,
            )
        )
        result["target_business_date"] = target_business_date
        result["as_of_business_date"] = as_of_business_date
        result["cross_business_date_fallback_allowed"] = False
        return result

    build_meituan_market_proxy._HISTORICAL_REPORT_DATE_SCOPE_V1 = True  # type: ignore[attr-defined]
    return build_meituan_market_proxy


def _first_date(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if len(text) >= 10:
            candidate = text[:10]
            try:
                datetime.fromisoformat(candidate)
            except ValueError:
                continue
            return candidate
    return None


def _replace_market_lines_for_scope_mismatch(text: str) -> str:
    lines = str(text or "").splitlines()
    output: list[str] = []
    inserted = False
    prefixes = ("- 美团大盘（估算）：", "- 美团估算份额：")
    for line in lines:
        if line.startswith(prefixes):
            if not inserted:
                output.extend(
                    [
                        "- 美团大盘（估算）：目标营业日与代理数据营业日不一致，本次不纳入。",
                        "- 美团估算份额：缺少同一营业日的估算分母，本次不判断。",
                    ]
                )
                inserted = True
            continue
        output.append(line)
    return "\n".join(output)


def _wrap_s16_message(previous: Callable[[Mapping[str, Any]], str]) -> Callable[[Mapping[str, Any]], str]:
    def render(report: Mapping[str, Any]) -> str:
        text = previous(report)
        dynamic = report.get("dynamic_diagnosis") or {}
        proxy = dynamic.get("meituan_market_proxy") or {}
        report_date = _first_date(
            dynamic.get("target_date"),
            report.get("target_date"),
            report.get("target_business_date"),
            report.get("business_date"),
            report.get("data_business_date"),
        )
        proxy_date = _first_date(proxy.get("target_business_date"))
        if (
            proxy.get("status") == "available"
            and report_date
            and proxy_date
            and report_date != proxy_date
        ):
            return _replace_market_lines_for_scope_mismatch(text)
        if report_date and report_date != _now_shanghai().date().isoformat():
            text = text.replace(
                "本店今日美团订单代理",
                "本店当日美团订单代理",
            )
        return text

    render._HISTORICAL_REPORT_DATE_SCOPE_V1 = True  # type: ignore[attr-defined]
    return render


def install_pre() -> None:
    global _INSTALLED_PRE
    if _INSTALLED_PRE:
        return
    _INSTALLED_PRE = True

    from runtime import s14_bundle_builder, s14_runtime_patch, time_context

    previous_resolver = time_context.resolve_request_as_of_time
    if not getattr(previous_resolver, "_HISTORICAL_REPORT_DATE_SCOPE_V1", False):
        wrapped_resolver = _wrap_time_resolver(previous_resolver)
        time_context.resolve_request_as_of_time = wrapped_resolver
    else:
        wrapped_resolver = previous_resolver

    previous_s14_detector = s14_bundle_builder.is_s14_operation_message
    if not getattr(
        previous_s14_detector,
        "_HISTORICAL_REPORT_DATE_SCOPE_V1",
        False,
    ):
        s14_bundle_builder.is_s14_operation_message = _wrap_s14_message_detector(
            previous_s14_detector
        )

    s14_runtime_patch._request_as_of = parse_s14_request_as_of

    # Import before S14 installs its route wrapper so auth/tenant gating sees
    # the historical report as an S14 business request from the start.
    from runtime import feishu_command_router as router

    router.resolve_request_as_of_time = wrapped_resolver
    previous_router_detector = router._detect_intent
    if not getattr(
        previous_router_detector,
        "_HISTORICAL_REPORT_DATE_SCOPE_V1",
        False,
    ):
        router._detect_intent = _wrap_router_detector(previous_router_detector)


def install_post() -> None:
    global _INSTALLED_POST
    if _INSTALLED_POST:
        return
    _INSTALLED_POST = True

    from runtime import (
        s15_s16_complete_output_patch,
        s15_s16_responsibility_patch,
        s16_meituan_projection_advisory_patch,
    )
    from runtime.sales_progress import presentation

    previous_proxy = s16_meituan_projection_advisory_patch.build_meituan_market_proxy
    if not getattr(previous_proxy, "_HISTORICAL_REPORT_DATE_SCOPE_V1", False):
        s16_meituan_projection_advisory_patch.build_meituan_market_proxy = (
            _wrap_market_proxy(previous_proxy)
        )

    previous_message = s15_s16_responsibility_patch._dynamic_message
    if not getattr(previous_message, "_HISTORICAL_REPORT_DATE_SCOPE_V1", False):
        wrapped_message = _wrap_s16_message(previous_message)
        s15_s16_responsibility_patch._dynamic_message = wrapped_message
        presentation.build_s16_user_message = wrapped_message
        s15_s16_complete_output_patch.s16_message = wrapped_message

    for module_name in (
        "runtime.time_context",
        "runtime.s14_runtime_patch",
        "runtime.s14_bundle_builder",
        "runtime.feishu_command_router",
        "runtime.s16_meituan_projection_advisory_patch",
    ):
        module = sys.modules.get(module_name)
        if module is not None:
            setattr(module, "HISTORICAL_REPORT_DATE_SCOPE_VERSION", VERSION)
