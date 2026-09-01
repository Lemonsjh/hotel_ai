from __future__ import annotations

import http.client
import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from runtime.adapters.nearby_events import load_database_nearby_events
from runtime.common import now_local


DEFAULT_MARKET_SOURCE_CONFIG = "/etc/hotel-ota-ai/market-source.json"
MARKET_SOURCE_CONFIG_ENV = "HOTEL_OTA_MARKET_SOURCE_CONFIG"
_WEATHER_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_EVENT_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def probe_market_provider_capability(provider: str, *, capabilities: dict[str, bool] | None = None) -> dict[str, Any]:
    declared = bool((capabilities or {}).get(provider))
    if provider == "openclaw_weather":
        return {"provider": provider, "available": declared, "reason": None if declared else "openclaw_weather_capability_not_available", "field_quality": "confirmed_exact" if declared else "missing", "decision_effect": "market_context_only"}
    if provider == "openclaw_search":
        return {"provider": provider, "available": declared, "reason": None if declared else "openclaw_search_capability_not_available", "field_quality": "search_inferred" if declared else "missing", "decision_effect": "confidence_only"}
    return {"provider": provider, "available": False, "reason": "market_provider_not_supported", "field_quality": "missing", "decision_effect": "none"}


def call_openclaw_weather(*, capability_call: Any | None = None, request: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if capability_call is None:
        return None, unavailable_weather("openclaw_weather", "openclaw_weather_capability_not_available")
    try:
        payload = capability_call("weather", request or {})
    except Exception as exc:
        return None, unavailable_weather("openclaw_weather", f"openclaw_weather_error:{exc.__class__.__name__}")
    if not isinstance(payload, dict):
        return None, unavailable_weather("openclaw_weather", "openclaw_weather_invalid_payload")
    return payload, {"status": "ok", "source": "openclaw_weather", "field_quality": "confirmed_exact", "source_quality": "provider"}


def call_openclaw_search(*, capability_call: Any | None = None, query: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if capability_call is None:
        return [], {"status": "data_gap", "source": "openclaw_search", "reason": "openclaw_search_capability_not_available", "field_quality": "missing"}
    try:
        payload = capability_call("search", {"query": query})
    except Exception as exc:
        return [], {"status": "data_gap", "source": "openclaw_search", "reason": f"openclaw_search_error:{exc.__class__.__name__}", "field_quality": "missing"}
    entries = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return [], {"status": "data_gap", "source": "openclaw_search", "reason": "openclaw_search_invalid_payload", "field_quality": "missing"}
    candidates = [
        {"event_id": f"search-{index}", "event_name": str(item.get("title") or item.get("name") or "candidate_event"), "source_url": item.get("url"), "status": "candidate", "field_quality": "search_inferred"}
        for index, item in enumerate(entries[:10], start=1)
        if isinstance(item, dict)
    ]
    return candidates, {"status": "partial", "source": "openclaw_search", "field_quality": "search_inferred", "source_quality": "partial", "decision_effect": "confidence_only", "direct_price_trigger_allowed": False}


def market_source_config_path(explicit_path: str | None = None) -> str | None:
    configured = explicit_path or os.environ.get(MARKET_SOURCE_CONFIG_ENV)
    if configured:
        return configured
    return DEFAULT_MARKET_SOURCE_CONFIG if os.path.exists(DEFAULT_MARKET_SOURCE_CONFIG) else None


def load_market_source_config(explicit_path: str | None = None) -> dict[str, Any]:
    path = market_source_config_path(explicit_path)
    if not path:
        return {"status": "missing", "reason": "market_source_config_not_configured"}
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {"status": "missing", "reason": "market_source_config_not_found"}
    except json.JSONDecodeError as exc:
        return {"status": "error", "reason": f"market_source_config_invalid_json:{exc.msg}"}
    if not isinstance(payload, dict):
        return {"status": "error", "reason": "market_source_config_must_be_object"}
    payload = dict(payload)
    payload["status"] = payload.get("status") or "ok"
    return payload


def market_config_for_hotel(config: dict[str, Any], hotel_id: str | None) -> dict[str, Any]:
    if config.get("status") != "ok":
        return {"status": "data_gap", "reason": config.get("reason") or "market_source_config_not_configured"}
    hotels = config.get("hotels")
    if isinstance(hotels, dict):
        tenant = hotels.get(hotel_id or "")
        if not isinstance(tenant, dict):
            return {"status": "data_gap", "reason": "tenant_market_config_not_found", "hotel_id": hotel_id}
        return {"status": "ok", "hotel_id": hotel_id, **tenant}
    return {"status": "ok", "hotel_id": hotel_id, **{key: value for key, value in config.items() if key != "hotels"}}


def market_source_diagnostics(config: dict[str, Any]) -> dict[str, Any]:
    tenant = {}
    hotels = config.get("hotels")
    if isinstance(hotels, dict) and hotels:
        first_key = sorted(hotels)[0]
        tenant = hotels.get(first_key) if isinstance(hotels.get(first_key), dict) else {}
    source = tenant or config
    weather = source.get("weather") or {}
    events = source.get("events") or {}
    holiday = source.get("holiday") or {}
    heat = source.get("regional_heat") or {}
    event_token_env = events.get("bearer_token_env")
    weather_key_env = weather.get("api_key_env") or "QWEATHER_API_KEY"
    return {
        "config_loaded": config.get("status") == "ok",
        "config_reason": config.get("reason"),
        "tenant_count": len(hotels) if isinstance(hotels, dict) else None,
        "weather_provider": weather.get("provider"),
        "weather_enabled": bool(weather.get("enabled", True)),
        "weather_key_configured": bool(os.environ.get(weather_key_env)),
        "weather_coordinates_configured": bool(weather.get("latitude") not in (None, "") and weather.get("longitude") not in (None, "")),
        "weather_location_configured": bool(weather.get("location")),
        "events_provider": events.get("provider"),
        "events_enabled": bool(events.get("enabled", True)),
        "events_path_configured": bool(events.get("path")),
        "events_endpoint_configured": bool(events.get("endpoint")),
        "events_database_table_configured": bool(events.get("provider") == "database_nearby_event"),
        "events_credential_configured": bool(event_token_env and os.environ.get(str(event_token_env))),
        "events_expected_service_id_configured": bool(events.get("expected_service_id")),
        "holiday_provider": holiday.get("provider"),
        "holiday_enabled": bool(holiday.get("enabled", False)),
        "holiday_commercial_use_confirmed": bool(holiday.get("commercial_use_confirmed")),
        "regional_heat_provider": heat.get("provider"),
        "regional_heat_enabled": bool(heat.get("enabled", True)),
    }


def event_bridge_status(config: dict[str, Any], *, hotel_id: str | None = None) -> dict[str, Any]:
    if not hotel_id and isinstance(config.get("hotels"), dict) and config["hotels"]:
        hotel_id = sorted(config["hotels"])[0]
    tenant = market_config_for_hotel(config, hotel_id)
    if tenant.get("status") != "ok":
        return {"provider": None, "enabled": False, "bridge_configured": False, "endpoint_configured": False, "endpoint_localhost": False, "token_status": "missing", "adapter_present": True, "runtime_service_verified": False, "reason": tenant.get("reason") or "tenant_market_config_not_found"}
    events = tenant.get("events") or {}
    provider = events.get("provider")
    endpoint = str(events.get("endpoint") or "")
    token_env = events.get("bearer_token_env")
    return {"provider": provider, "enabled": bool(events.get("enabled", True)), "bridge_configured": provider == "openclaw_bridge_http_search", "endpoint_configured": bool(endpoint), "endpoint_localhost": bool(endpoint and _is_local_bridge_endpoint(endpoint)), "token_status": "set" if token_env and os.environ.get(str(token_env)) else "missing", "adapter_present": True, "runtime_service_verified": False, "expected_service_id_configured": bool(events.get("expected_service_id")), "reason": None}


def _event_date(item: dict[str, Any]) -> str | None:
    return item.get("date") or item.get("business_date") or item.get("day") or item.get("event_start_date")


def _normalize_events(payload: Any) -> list[dict[str, Any]]:
    events = payload.get("events") if isinstance(payload, dict) else payload
    if isinstance(payload, dict) and events is None:
        events = payload.get("results")
    if not isinstance(events, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in events:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "event_id": item.get("event_id"),
            "date": _event_date(item),
            "event_name": item.get("event_name") or item.get("name") or item.get("title") or "unknown_event",
            "event_type": item.get("event_type") or item.get("type"),
            "location": item.get("location"),
            "distance_km": item.get("distance_km"),
            "source_url": item.get("source_url") or item.get("url"),
            "confidence": float(item.get("confidence") or 0),
            "expected_heat": item.get("expected_heat") or item.get("heat") or "unknown",
            "status": item.get("status") or "candidate",
            "direct_price_trigger_allowed": bool(item.get("direct_price_trigger_allowed", False)),
        })
    return normalized


def _range_bounds(date_range: str | None, business_date: str | None = None) -> tuple[str | None, str | None]:
    if date_range and ".." in date_range:
        start, end = date_range.split("..", 1)
        return start.strip() or None, end.strip() or None
    if date_range:
        value = date_range.strip()
        return value, value
    return business_date, business_date


def _verified_event_payload(endpoint: str, token: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _valid_verified_event_payload(payload: Any) -> bool:
    if not isinstance(payload, dict) or not payload.get("source_id") or not payload.get("fetched_at") or not isinstance(payload.get("events"), list):
        return False
    for event in payload["events"]:
        if not isinstance(event, dict):
            return False
        if any(not event.get(field) for field in ("event_id", "date", "confidence")):
            return False
    return True


def _verified_events_for_period(payload: dict[str, Any], *, business_date: str | None, date_range: str | None) -> list[dict[str, Any]]:
    events = _normalize_events(payload)
    start, end = _range_bounds(date_range, business_date)
    if start and end:
        return [item for item in events if item.get("date") and start <= str(item["date"]) <= end]
    return events


def load_verified_http_events(config: dict[str, Any], *, hotel_id: str, business_date: str | None = None, date_range: str | None = None, http_get: Any | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tenant = market_config_for_hotel(config, hotel_id)
    if tenant.get("status") != "ok":
        return [], {"status": "data_gap", "source": "verified_http_json", "reason": tenant.get("reason")}
    events_config = tenant.get("events") or {}
    if events_config.get("provider") != "verified_http_json" or not events_config.get("enabled", True):
        return [], {"status": "data_gap", "source": events_config.get("provider") or "verified_http_json", "reason": "event_discovery_provider_not_configured"}
    endpoint = str(events_config.get("endpoint") or "")
    if not endpoint.startswith("https://"):
        return [], {"status": "data_gap", "source": "verified_http_json", "reason": "event_provider_https_required"}
    token = os.environ.get(str(events_config.get("bearer_token_env") or ""))
    if not token:
        return [], {"status": "data_gap", "source": "verified_http_json", "reason": "event_provider_not_configured"}
    timeout_seconds = float(events_config.get("timeout_seconds") or 5)
    ttl_value = events_config.get("cache_ttl_seconds")
    ttl_seconds = 21600.0 if ttl_value is None else float(ttl_value)
    cache_key = (hotel_id, endpoint)
    cached = _EVENT_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < ttl_seconds:
        return _verified_events_for_period(cached[1], business_date=business_date, date_range=date_range), {"status": "ok", "source": "verified_http_json", "event_source": cached[1]["source_id"], "fetched_at": cached[1]["fetched_at"], "cache_status": "fresh_cache", "stale": False}
    try:
        payload = http_get(endpoint, token, timeout_seconds) if http_get else _verified_event_payload(endpoint, token, timeout_seconds)
    except Exception as exc:
        if cached:
            return _verified_events_for_period(cached[1], business_date=business_date, date_range=date_range), {"status": "partial", "source": "verified_http_json", "event_source": cached[1]["source_id"], "fetched_at": cached[1]["fetched_at"], "cache_status": "stale_cache", "stale": True, "reason": "event_provider_stale_cache"}
        return [], {"status": "data_gap", "source": "verified_http_json", "reason": f"event_provider_error:{exc.__class__.__name__}"}
    if not _valid_verified_event_payload(payload):
        return [], {"status": "data_gap", "source": "verified_http_json", "reason": "event_provider_invalid_schema"}
    _EVENT_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return _verified_events_for_period(payload, business_date=business_date, date_range=date_range), {"status": "ok", "source": "verified_http_json", "event_source": payload["source_id"], "fetched_at": payload["fetched_at"], "cache_status": "network", "stale": False}


def load_manual_events(config: dict[str, Any], *, date_range: str | None = None, business_date: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events_config = config.get("events") or {}
    provider = events_config.get("provider") or "manual_json"
    if config.get("status") != "ok":
        return [], {"status": "data_gap", "source": provider, "reason": config.get("reason") or "market_source_config_not_configured"}
    if not events_config.get("enabled", True):
        return [], {"status": "data_gap", "source": provider, "reason": "event_discovery_provider_disabled"}
    if provider != "manual_json":
        return [], {"status": "data_gap", "source": provider, "reason": "event_discovery_provider_not_supported"}
    path = events_config.get("path")
    if not path:
        return [], {"status": "data_gap", "source": provider, "reason": "event_discovery_provider_not_configured"}
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            events = _normalize_events(json.load(handle))
    except FileNotFoundError:
        return [], {"status": "data_gap", "source": provider, "reason": "event_discovery_provider_not_configured"}
    except json.JSONDecodeError as exc:
        return [], {"status": "data_gap", "source": provider, "reason": f"event_discovery_invalid_json:{exc.msg}"}
    start, end = _range_bounds(date_range, business_date)
    if start and end:
        events = [item for item in events if item.get("date") and start <= str(item.get("date")) <= end]
    return events, {"status": "ok", "source": provider, "reason": None}


def _is_local_bridge_endpoint(endpoint: str) -> bool:
    parsed = urllib.parse.urlparse(endpoint)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}


def load_openclaw_bridge_events(config: dict[str, Any], *, hotel_id: str, business_date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events_config = config.get("events") or {}
    if not events_config.get("enabled", True):
        return [], {"status": "data_gap", "source": "openclaw_bridge_http_search", "reason": "event_discovery_provider_disabled", "field_quality": "missing"}
    endpoint = str(events_config.get("endpoint") or "")
    if not endpoint:
        return [], {"status": "data_gap", "source": "openclaw_bridge_http_search", "reason": "market_bridge_endpoint_not_configured", "field_quality": "missing"}
    if not _is_local_bridge_endpoint(endpoint):
        return [], {"status": "data_gap", "source": "openclaw_bridge_http_search", "reason": "market_bridge_endpoint_not_localhost", "field_quality": "missing"}
    token_env = events_config.get("bearer_token_env")
    token = os.environ.get(str(token_env)) if token_env else None
    if not token:
        return [], {"status": "data_gap", "source": "openclaw_bridge_http_search", "reason": "market_bridge_token_not_configured", "field_quality": "missing", "source_quality": "demo_or_untrusted"}
    query_template = events_config.get("query_template") or "{business_date} {hotel_id} 周边活动"
    query = str(query_template).format(business_date=business_date, hotel_id=hotel_id)
    body = json.dumps({"hotel_id": hotel_id, "business_date": business_date, "query": query}, ensure_ascii=False).encode("utf-8")
    timeout = float(events_config.get("timeout_seconds") or 5)
    try:
        parsed = urllib.parse.urlparse(endpoint)
        conn = http.client.HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port or 80, timeout=timeout)
        try:
            path = parsed.path or "/search"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            conn.request("POST", path, body=body, headers={"Content-Type": "application/json", "X-Hotel-Ota-Bridge": "event-search", "Authorization": f"Bearer {token}"})
            payload = json.loads(conn.getresponse().read().decode("utf-8"))
        finally:
            conn.close()
    except Exception as exc:
        return [], {"status": "data_gap", "source": "openclaw_bridge_http_search", "reason": f"market_bridge_error:{exc.__class__.__name__}", "field_quality": "missing"}
    expected_service_id = events_config.get("expected_service_id") or "hotel-ota-event-search-bridge"
    if not isinstance(payload, dict) or payload.get("service_id") != expected_service_id:
        return [], {"status": "data_gap", "source": "openclaw_bridge_http_search", "reason": "market_bridge_untrusted_service_id", "field_quality": "missing", "source_quality": "demo_or_untrusted"}
    events = _normalize_events(payload)
    if not events:
        return [], {"status": "data_gap", "source": "openclaw_bridge_http_search", "reason": "market_bridge_no_events", "field_quality": "missing", "source_quality": "partial_verified"}
    return events, {"status": "partial", "source": "openclaw_bridge_http_search", "event_source": "openclaw_bridge_http_search", "field_quality": "search_inferred", "source_quality": "partial_verified", "direct_price_trigger_allowed": False, "reason": None}


def build_event_context(config: dict[str, Any], *, business_date: str, hotel_id: str | None = None) -> dict[str, Any]:
    tenant = market_config_for_hotel(config, hotel_id)
    if tenant.get("status") != "ok":
        return {
            "status": "data_gap",
            "data_gap_type": "event_data_gap",
            "event_data_gap": True,
            "event_source": "unconfigured",
            "source": "unconfigured",
            "reason": tenant.get("reason"),
            "local_event_count": 0,
            "event_signal": "unknown",
            "event_heat_level": "unknown",
            "events": [],
            "event_candidates": [],
            "direct_price_trigger_allowed": False,
        }
    provider = (tenant.get("events") or {}).get("provider") or "manual_json"
    if provider == "verified_http_json":
        events, meta = load_verified_http_events(config, hotel_id=str(hotel_id or ""), business_date=business_date)
    elif provider == "openclaw_search":
        events, meta = call_openclaw_search(query=f"{business_date} hotel events")
    elif provider == "openclaw_bridge_http_search":
        events, meta = load_openclaw_bridge_events(tenant, hotel_id=str(hotel_id or ""), business_date=business_date)
    elif provider == "database_nearby_event":
        events, meta = load_database_nearby_events(tenant, hotel_id=str(hotel_id or ""), business_date=business_date)
    else:
        events, meta = load_manual_events(tenant, business_date=business_date)
    if meta.get("status") not in {"ok", "partial"}:
        return {
            "status": "data_gap",
            "data_gap_type": "event_data_gap",
            "event_data_gap": True,
            "event_source": meta.get("source") or provider,
            "source": meta.get("source") or provider,
            "reason": meta.get("reason") or "event_discovery_provider_not_configured",
            "local_event_count": 0,
            "event_signal": "unknown",
            "event_heat_level": "unknown",
            "events": [],
            "event_candidates": [],
            "direct_price_trigger_allowed": False,
        }
    heat_order = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
    heat = "unknown"
    for item in events:
        expected = str(item.get("expected_heat") or "unknown")
        if heat_order.get(expected, 0) > heat_order.get(heat, 0):
            heat = expected
    signal = "strong" if heat == "high" else "moderate" if heat == "medium" else "neutral"
    return {
        "status": meta.get("status") or "ok",
        "event_source": meta.get("event_source") or provider,
        "source": meta.get("source") or provider,
        "reason": meta.get("reason"),
        "cache_status": meta.get("cache_status"),
        "stale": bool(meta.get("stale")),
        "local_event_count": len(events),
        "event_signal": signal,
        "event_heat_level": heat,
        "events": events[:5],
        "event_candidates": events[:5] if provider in {"openclaw_search", "openclaw_bridge_http_search"} else [],
        "field_quality": meta.get("field_quality") or "confirmed_exact",
        "source_quality": meta.get("source_quality") or ("partial" if meta.get("status") == "partial" else "confirmed"),
        "direct_price_trigger_allowed": bool(meta.get("direct_price_trigger_allowed", False)),
        "data_snapshot_time": meta.get("data_snapshot_time"),
        "tenant_filter_mode": meta.get("tenant_filter_mode"),
        "risk_flags": list(meta.get("risk_flags") or []),
        "data_status": meta.get("data_status") or meta.get("status") or "ok",
    }


def _score_event_heat(event_context: dict[str, Any]) -> float | None:
    if event_context.get("status") not in {"ok", "partial"}:
        return None
    heat = event_context.get("event_heat_level") or "unknown"
    base = {"high": 90, "medium": 65, "low": 35, "unknown": 50}.get(str(heat), 50)
    count_bonus = min(int(event_context.get("local_event_count") or 0) * 5, 10)
    return min(100.0, base + count_bonus)


def _score_from_context(context: dict[str, Any] | None, keys: tuple[str, ...], scale: float = 100.0) -> float | None:
    if not isinstance(context, dict):
        return None
    for key in keys:
        value = context.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number <= 1:
            number *= scale
        return max(0.0, min(100.0, number))
    return None


def build_regional_heat_context(config: dict[str, Any], *, hotel_id: str | None = None, event_context: dict[str, Any], operating_context: dict[str, Any] | None = None, progress_context: dict[str, Any] | None = None, competitor_context: dict[str, Any] | None = None) -> dict[str, Any]:
    tenant = market_config_for_hotel(config, hotel_id)
    if tenant.get("status") != "ok":
        return {"status": "data_gap", "source": "composite", "regional_heat_source": "composite", "reason": tenant.get("reason") or "tenant_market_config_not_found", "regional_heat_index": None, "component_scores": {}, "missing_fields": ["regional_heat"]}
    heat_config = tenant.get("regional_heat") or {}
    provider = heat_config.get("provider") or "composite"
    if provider != "composite" or not heat_config.get("enabled", True):
        return {"status": "data_gap", "source": provider, "regional_heat_source": provider, "reason": "regional_heat_provider_not_configured", "regional_heat_index": None, "component_scores": {}, "missing_fields": ["regional_heat"]}
    component_scores = {
        "event_heat": _score_event_heat(event_context),
        "ota_conversion": _score_from_context(operating_context, ("conversion_rate", "ota_conversion_rate", "pay_conversion_rate")),
        "historical_same_period": _score_from_context(operating_context, ("historical_demand_index", "same_period_demand_index")),
        "competitor_signal": _score_from_context(competitor_context, ("competitor_heat_index", "our_price_index")),
        "booking_progress": _score_from_context(progress_context, ("completion_rate", "booking_progress", "progress_rate")),
    }
    weights = heat_config.get("weights") or {"event_heat": 0.25, "ota_conversion": 0.25, "historical_same_period": 0.2, "competitor_signal": 0.15, "booking_progress": 0.15}
    available = {key: value for key, value in component_scores.items() if value is not None}
    missing = [key for key, value in component_scores.items() if value is None]
    if not available:
        return {"status": "data_gap", "source": "composite", "regional_heat_source": "composite", "regional_heat_index": None, "component_scores": component_scores, "missing_fields": missing, "source_quality": "missing"}
    total_weight = sum(float(weights.get(key, 0)) for key in available) or len(available)
    score = sum(float(weights.get(key, 1)) * value for key, value in available.items()) / total_weight
    return {"status": "ok" if not missing else "partial", "source": "composite", "regional_heat_source": "composite", "regional_heat_index": round(score, 2), "component_scores": component_scores, "missing_fields": missing, "source_quality": "mixed" if missing else "confirmed", "computed_at": now_local()}


def _qweather_now(config: dict[str, Any]) -> dict[str, Any] | None:
    key_env = config.get("api_key_env") or "QWEATHER_API_KEY"
    key = os.environ.get(key_env)
    location = config.get("location")
    if not key or not location:
        return None
    host = config.get("api_host") or "https://devapi.qweather.com"
    cache_key = (str(host), str(location))
    ttl_seconds = float(config.get("cache_ttl_seconds") or 900)
    cached = _WEATHER_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < ttl_seconds:
        return dict(cached[1])
    url = f"{host.rstrip()}/v7/weather/now?{urllib.parse.urlencode({'location': location, 'key': key})}"
    with urllib.request.urlopen(url, timeout=float(config.get("timeout_seconds") or 5)) as response:
        payload = json.loads(response.read().decode("utf-8"))
    _WEATHER_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return payload


def _wttr_now(config: dict[str, Any]) -> dict[str, Any] | None:
    location = str(config.get("location") or "").strip()
    if not location:
        return None
    cache_key = ("wttr_http", location)
    ttl_seconds = float(config.get("cache_ttl_seconds") or 900)
    cached = _WEATHER_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < ttl_seconds:
        return dict(cached[1])
    url = f"https://wttr.in/{urllib.parse.quote(location)}?{urllib.parse.urlencode({'format': 'j1'})}"
    with urllib.request.urlopen(url, timeout=float(config.get("timeout_seconds") or 5)) as response:
        payload = json.loads(response.read().decode("utf-8"))
    _WEATHER_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return payload


def _open_meteo_now(config: dict[str, Any]) -> dict[str, Any] | None:
    latitude = config.get("latitude")
    longitude = config.get("longitude")
    if latitude in (None, "") or longitude in (None, ""):
        return None
    timezone = str(config.get("timezone") or "auto")
    cache_key = ("open_meteo", str(latitude), str(longitude), timezone)
    ttl_seconds = float(config.get("cache_ttl_seconds") or 900)
    cached = _WEATHER_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < ttl_seconds:
        return dict(cached[1])
    host = config.get("api_host") or "https://api.open-meteo.com"
    current_fields = ",".join(["temperature_2m", "apparent_temperature", "precipitation", "rain", "showers", "weather_code", "cloud_cover", "wind_speed_10m"])
    params = {"latitude": latitude, "longitude": longitude, "timezone": timezone, "current": current_fields}
    api_key_env = config.get("api_key_env")
    if api_key_env and os.environ.get(str(api_key_env)):
        params["apikey"] = os.environ[str(api_key_env)]
    url = f"{str(host).rstrip('/')}/v1/forecast?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=float(config.get("timeout_seconds") or 5)) as response:
        payload = json.loads(response.read().decode("utf-8"))
    payload.setdefault("source", "open_meteo")
    payload.setdefault("display_location", config.get("display_location") or config.get("location"))
    payload.setdefault("latitude", latitude)
    payload.setdefault("longitude", longitude)
    payload.setdefault("timezone", timezone)
    _WEATHER_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return payload


def resolve_weather_payload(config: dict[str, Any], *, hotel_id: str | None = None) -> tuple[dict[str, Any] | None, str, str | None]:
    tenant = market_config_for_hotel(config, hotel_id)
    if tenant.get("status") != "ok":
        return None, "qweather_api", tenant.get("reason") or "tenant_market_config_not_found"
    weather = tenant.get("weather") or {}
    provider = weather.get("provider") or "qweather_api"
    if not weather.get("enabled", True):
        return None, provider, "weather_provider_disabled"
    try:
        if provider == "openclaw_weather":
            payload, meta = call_openclaw_weather()
            return payload, provider, meta.get("reason")
        if provider == "qweather_api":
            if not os.environ.get(weather.get("api_key_env") or "QWEATHER_API_KEY"):
                return None, provider, "weather_provider_not_configured"
            if not weather.get("location"):
                return None, provider, "weather_location_not_configured"
            return _qweather_now(weather), provider, None
        if provider == "wttr_http":
            if not weather.get("location"):
                return None, provider, "weather_location_not_configured"
            return _wttr_now(weather), provider, None
        if provider == "open_meteo":
            if weather.get("latitude") in (None, "") or weather.get("longitude") in (None, ""):
                return None, provider, "weather_coordinates_not_configured"
            return _open_meteo_now(weather), provider, None
        if provider in {"manual_weather", "weather_fixture"}:
            path = weather.get("path") or weather.get("fixture")
            if not path and any(weather.get(key) not in (None, "") for key in ("condition", "text", "weather_summary", "temperature_c", "temp")):
                return {"now": {"text": weather.get("condition") or weather.get("text") or weather.get("weather_summary") or "manual weather", "temp": weather.get("temperature_c") or weather.get("temp")}, "source": provider}, provider, None
            if not path:
                return None, provider, "weather_provider_not_configured"
            with open(path, "r", encoding="utf-8-sig") as handle:
                return json.load(handle), provider, None
    except Exception as exc:
        if provider == "open_meteo":
            for fallback in weather.get("fallback_providers") or []:
                if fallback == "wttr_http" and weather.get("location"):
                    try:
                        return _wttr_now(weather), "open_meteo_failed_fallback_wttr_http", None
                    except Exception:
                        continue
        return None, provider, f"weather_provider_error:{exc.__class__.__name__}"
    return None, provider, "weather_provider_not_supported"


def unavailable_weather(provider: str, reason: str | None) -> dict[str, Any]:
    return {"status": "unavailable", "source": provider, "reason": reason or "weather_provider_not_configured", "weather_summary": "weather source unavailable", "weather_signal": "unknown", "weather_risk_level": "unknown", "source_quality": "unavailable", "field_quality": "missing"}
