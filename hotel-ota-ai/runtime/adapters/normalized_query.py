from __future__ import annotations

from collections import defaultdict
from typing import Any


PLATFORM_ALIASES = {
    "meituan": "meituan",
    "美团": "meituan",
    "mt": "meituan",
    "ctrip": "ctrip",
    "携程": "ctrip",
    "xiecheng": "ctrip",
    "去哪儿": "qunar",
    "qunar": "qunar",
    "pms（别样红）": "pms",
    "pms(别样红)": "pms",
    "别样红": "pms",
    "pms_byh": "pms",
    "pms": "pms",
    "散客": "walkin",
    "walkin": "walkin",
    "walk-in": "walkin",
    "direct": "walkin",
    "": "walkin",
}

AUTO_MAPPING_STATUS = "AUTO"
TRUSTED_PRICE_MAPPING_RULES = {"MANUAL", "ROOM_ID", "PRODUCT_ID", "GOODS_ID"}
MAPPING_PENDING_STATUSES = {
    "",
    "PENDING",
    "CONFIRMED",
    "CONFLICT",
    "REJECTED",
    "CANDIDATE",
    "MAPPING_CANDIDATE",
}
DISABLED_PRICE_TASK_PLATFORMS = {"disabled", "unknown"}


def normalize_source_platform(value: Any) -> str:
    text = str(value or "").strip()
    return PLATFORM_ALIASES.get(text, PLATFORM_ALIASES.get(text.lower(), text.lower() or "walkin"))


def is_trusted_price_mapping(row: dict[str, Any]) -> bool:
    """Whether the mapping has an auditable exact-match signal for price writes."""
    status = str(_value(row, "mapping_status") or "").strip().upper()
    match_rule = str(_value(row, "match_rule") or "").strip().upper()
    return status == "CONFIRMED" or match_rule in TRUSTED_PRICE_MAPPING_RULES


def price_task_mapping_trust_basis(row: dict[str, Any]) -> str:
    """Return the auditable trust basis used by a price-task write gate."""
    status = str(_value(row, "mapping_status") or "").strip().upper()
    match_rule = str(_value(row, "match_rule") or "").strip().upper()
    if status == "CONFIRMED":
        return "confirmed_mapping"
    if match_rule in TRUSTED_PRICE_MAPPING_RULES:
        return f"exact_match_rule:{match_rule.lower()}"
    return "not_trusted"


# 房型名称桶键归一:把分隔符变体(·/./．/・/‧)统一为同一字符(不删除,避免
# "101.5房"→"1015房" 与不同房型相撞),全角括号→半角,去空白。
# 使 至臻·电竞双床房(PMS,·=U+00B7) 与 至臻.电竞双床房(美团,.=U+002E) 归一为同键。
_NAME_KEY_TRANSLATION = str.maketrans(
    {
        "·": "·",  # · MIDDLE DOT(canonical)
        ".": "·",       # . FULL STOP → 中点
        "．": "·",  # ． FULLWIDTH FULL STOP → 中点
        "・": "·",  # ・ KATAKANA MIDDLE DOT → 中点
        "‧": "·",  # ‧ HYPHENATION POINT → 中点
        " ": None,
        "　": None,  # 全角空格
        "（": "(",   # （ → (
        "）": ")",   # ） → )
    }
)


def _normalize_name_key(name: Any) -> str:
    return str(name or "").strip().translate(_NAME_KEY_TRANSLATION)


def _value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) == 1.0
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "active"}:
        return True
    if text in {"0", "false", "no", "n", "inactive"}:
        return False
    try:
        return float(text) == 1.0
    except ValueError:
        return False


def _normalized_mapping_row(row: dict[str, Any]) -> dict[str, Any]:
    source_platform = normalize_source_platform(_value(row, "source_platform", "channel_source", "platform"))
    return {
        **row,
        "mapping_id": _value(row, "mapping_id", "id"),
        "hotel_id": _value(row, "hotel_id"),
        "hotel_name": _value(row, "hotel_name"),
        "room_type_id": _value(row, "room_type_id", "pms_room_type_id"),
        "room_type_name": _value(row, "room_type_name", "pms_room_type_name"),
        "source_platform": source_platform,
        "source_room_type_id": _value(row, "source_room_type_id", "ota_room_type_id"),
        "source_room_type_name": _value(row, "source_room_type_name", "ota_room_type_name", "room_type_name"),
        "source_product_id": _value(row, "source_product_id", "ota_product_id"),
        "source_product_name": _value(row, "source_product_name", "ota_product_name"),
        "mapping_status": str(_value(row, "mapping_status") or "").strip().upper(),
        "match_rule": str(_value(row, "match_rule") or "").strip().upper(),
        "mapping_active": _truthy(_value(row, "mapping_active", "is_active", "active")),
        "price_editable_flag": _value(row, "price_editable_flag"),
        "is_hour_room": _value(row, "is_hour_room"),
        "product_cipher": _value(row, "product_cipher"),
    }


def build_room_mapping_index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    index: dict[str, Any] = {
        "hotel_product": defaultdict(list),
        "hotel_room_type": defaultdict(list),
        "hotel_room_name": defaultdict(list),
        "legacy_product": defaultdict(list),
        "legacy_room_name": defaultdict(list),
        "rows": [],
    }
    for raw in rows:
        row = _normalized_mapping_row(dict(raw))
        index["rows"].append(row)
        hotel_id = str(row.get("hotel_id") or "").strip()
        hotel_name = str(row.get("hotel_name") or "").strip()
        platform = normalize_source_platform(row.get("source_platform"))
        product_id = str(row.get("source_product_id") or "").strip()
        source_room_type_id = str(row.get("source_room_type_id") or "").strip()
        source_room_type_name = str(row.get("source_room_type_name") or row.get("room_type_name") or "").strip()
        name_key = _normalize_name_key(source_room_type_name)
        if hotel_id and product_id:
            index["hotel_product"][(hotel_id, platform, product_id)].append(row)
        if hotel_id and source_room_type_id:
            index["hotel_room_type"][(hotel_id, platform, source_room_type_id)].append(row)
        if hotel_id and name_key:
            index["hotel_room_name"][(hotel_id, platform, name_key)].append(row)
        if hotel_name and product_id:
            index["legacy_product"][(hotel_name, platform, product_id)].append(row)
        if hotel_name and name_key:
            index["legacy_room_name"][(hotel_name, platform, name_key)].append(row)
    return index


def _legacy_names(profile: dict[str, Any], hotel_id: str | None) -> set[str]:
    names: set[str] = set()
    if not hotel_id:
        return names
    configured = profile.get("legacy_hotel_names") or profile.get("hotel_names") or {}
    value = configured.get(hotel_id) if isinstance(configured, dict) else None
    if isinstance(value, str):
        names.add(value)
    elif isinstance(value, list):
        names.update(str(item) for item in value if item)
    hotels = profile.get("hotel_ids") or {}
    hotel = hotels.get(hotel_id) if isinstance(hotels, dict) else None
    if isinstance(hotel, dict):
        for key in ("hotel_name", "display_name", "name"):
            if hotel.get(key):
                names.add(str(hotel[key]))
        aliases = hotel.get("aliases") or hotel.get("hotel_aliases") or []
        if isinstance(aliases, str):
            names.add(aliases)
        elif isinstance(aliases, list):
            names.update(str(item) for item in aliases if item)
    elif isinstance(hotel, str):
        names.add(hotel)
    if profile.get("hotel_name"):
        names.add(str(profile["hotel_name"]))
    return {item.strip() for item in names if item and item.strip()}


def resolve_hotel_scope(raw_row: dict[str, Any], requested_hotel_id: str | None, profile: dict[str, Any]) -> dict[str, Any]:
    has_hotel_id_field = "hotel_id" in raw_row
    row_hotel_id = _value(raw_row, "hotel_id")
    row_hotel_name = _value(raw_row, "hotel_name")
    risks: list[str] = []
    if row_hotel_id:
        if requested_hotel_id and str(row_hotel_id) != str(requested_hotel_id):
            return {
                "hotel_id": requested_hotel_id,
                "tenant_filter_mode": "unresolved",
                "mapping_resolution_status": "data_gap",
                "risk_flags": ["tenant_scope_mismatch"],
            }
        return {
            "hotel_id": str(row_hotel_id),
            "tenant_filter_mode": "hotel_id",
            "mapping_resolution_status": "mapped",
            "risk_flags": risks,
        }
    legacy_names = _legacy_names(profile, requested_hotel_id)
    if row_hotel_name and str(row_hotel_name).strip() in legacy_names:
        return {
            "hotel_id": requested_hotel_id,
            "tenant_filter_mode": "hotel_id_empty_hotel_name_legacy" if has_hotel_id_field else "hotel_name_legacy",
            "mapping_resolution_status": "mapped",
            "risk_flags": ["legacy_hotel_name_filter"],
        }
    return {
        "hotel_id": requested_hotel_id,
        "tenant_filter_mode": "unresolved",
        "mapping_resolution_status": "data_gap",
        "risk_flags": ["tenant_scope_unresolved"],
    }


def _pick_candidate(candidates: list[dict[str, Any]], *, candidate_only: bool = False) -> dict[str, Any]:
    if not candidates:
        return {
            "mapping_resolution_status": "mapping_pending",
            "mapping_status": None,
            "mapping_active": False,
            "risk_flags": ["mapping_pending"],
        }

    # 价格写路径只接受已确认映射，或由可信精确规则得到的映射。
    # 名称候选、冲突和未审核映射不能与可信映射混用。
    trusted_candidates = [item for item in candidates if is_trusted_price_mapping(item)]
    if not trusted_candidates:
        statuses = sorted(
            {
                str(item.get("mapping_status") or "").strip().upper() or "EMPTY"
                for item in candidates
            }
        )
        return {
            "mapping_resolution_status": "mapping_not_trusted",
            "mapping_status": statuses[0] if len(statuses) == 1 else "MIXED_NON_AUTO",
            "mapping_active": False,
            "risk_flags": ["mapping_not_trusted", "price_task_blocked"],
        }

    # Active trusted mappings take precedence; inactive ones remain diagnosable.
    active_candidates = [item for item in trusted_candidates if bool(item.get("mapping_active"))]
    selected = active_candidates or trusted_candidates
    if len(selected) > 1:
        return {
            "mapping_resolution_status": "mapping_conflict",
            "mapping_status": "CONFLICT",
            "mapping_active": False,
            "risk_flags": ["mapping_conflict", "price_task_blocked"],
        }

    item = selected[0]
    active = bool(item.get("mapping_active"))
    if candidate_only:
        # 名称反推只用于展示/诊断。覆盖状态为 CANDIDATE，避免下游把原始
        # AUTO 状态误当成精确商品映射后进入真实写入。
        return {
            **_public_mapping_fields(item, expose_room_type=True),
            "mapping_status": "CANDIDATE",
            "match_rule": None,
            "mapping_resolution_status": "mapping_pending",
            "risk_flags": ["mapping_candidate_name_match", "inferred_by_name", "price_task_blocked"],
        }
    if not active:
        return {
            **_public_mapping_fields(item, expose_room_type=False),
            "mapping_resolution_status": "mapping_inactive",
            "risk_flags": ["mapping_inactive", "price_task_blocked"],
        }
    if not item.get("room_type_id"):
        return {
            **_public_mapping_fields(item, expose_room_type=False),
            "mapping_resolution_status": "mapping_pending",
            "risk_flags": ["mapping_pending", "price_task_blocked"],
        }
    return {
        **_public_mapping_fields(item, expose_room_type=True),
        "mapping_resolution_status": "mapped",
        "risk_flags": [],
    }


def _public_mapping_fields(item: dict[str, Any], *, expose_room_type: bool) -> dict[str, Any]:
    return {
        "mapping_id": item.get("mapping_id"),
        "mapping_status": item.get("mapping_status"),
        "match_rule": item.get("match_rule"),
        "mapping_active": bool(item.get("mapping_active")),
        "room_type_id": item.get("room_type_id") if expose_room_type else None,
        "room_type_name": item.get("room_type_name") if expose_room_type else item.get("room_type_name"),
        "source_room_type_id": item.get("source_room_type_id"),
        "source_product_id": item.get("source_product_id"),
        "source_product_name": item.get("source_product_name"),
        "price_editable_flag": item.get("price_editable_flag"),
        "is_hour_room": item.get("is_hour_room"),
        "product_cipher": item.get("product_cipher"),
    }


def resolve_room_type_mapping(raw_row: dict[str, Any], mapping_index: dict[str, Any]) -> dict[str, Any]:
    platform = normalize_source_platform(_value(raw_row, "source_platform", "channel_source", "platform"))
    hotel_id = _value(raw_row, "hotel_id")
    hotel_name = _value(raw_row, "hotel_name")
    product_id = str(_value(raw_row, "source_product_id", "ota_product_id") or "").strip()
    source_room_type_id = str(_value(raw_row, "source_room_type_id", "ota_room_type_id") or "").strip()
    source_room_type_name = str(_value(raw_row, "source_room_type_name", "ota_room_type_name", "room_type_name") or "").strip()
    name_key = _normalize_name_key(source_room_type_name)

    if hotel_id and product_id:
        found = _pick_candidate(mapping_index.get("hotel_product", {}).get((str(hotel_id), platform, product_id), []))
        if found.get("mapping_resolution_status") != "mapping_pending" or found.get("mapping_id"):
            return found
    if hotel_id and source_room_type_id:
        found = _pick_candidate(mapping_index.get("hotel_room_type", {}).get((str(hotel_id), platform, source_room_type_id), []))
        if found.get("mapping_resolution_status") != "mapping_pending" or found.get("mapping_id"):
            return found
    if hotel_id and name_key:
        found = _pick_candidate(mapping_index.get("hotel_room_name", {}).get((str(hotel_id), platform, name_key), []), candidate_only=True)
        if found.get("mapping_id"):
            return found
    if hotel_name and product_id:
        found = _pick_candidate(mapping_index.get("legacy_product", {}).get((str(hotel_name), platform, product_id), []), candidate_only=True)
        if found.get("mapping_id"):
            return found
    if hotel_name and name_key:
        found = _pick_candidate(mapping_index.get("legacy_room_name", {}).get((str(hotel_name), platform, name_key), []), candidate_only=True)
        if found.get("mapping_id"):
            return found
    return _pick_candidate([])


def _normalized_base_row(raw_row: dict[str, Any], mapping_index: dict[str, Any], requested_hotel_id: str | None, profile: dict[str, Any]) -> dict[str, Any]:
    row = dict(raw_row)
    source_room_type_id = _value(row, "room_type_id", "pms_room_type_id")
    row["source_platform"] = normalize_source_platform(_value(row, "source_platform", "channel_source", "platform"))
    row["source_room_type_id"] = _value(row, "source_room_type_id", "ota_room_type_id")
    row["source_room_type_name"] = _value(row, "source_room_type_name", "ota_room_type_name", "room_type_name")
    row["source_product_id"] = _value(row, "source_product_id", "ota_product_id")
    row["source_product_name"] = _value(row, "source_product_name", "ota_product_name")
    hotel_scope = resolve_hotel_scope(row, requested_hotel_id, profile)
    if hotel_scope.get("hotel_id"):
        row["hotel_id"] = hotel_scope["hotel_id"]
    mapping = resolve_room_type_mapping(row, mapping_index)
    risk_flags = list(dict.fromkeys([*(hotel_scope.get("risk_flags") or []), *(mapping.get("risk_flags") or [])]))
    source_has_product = _value(row, "source_product_id", "ota_product_id") not in (None, "")
    source_mapping_status = mapping.get("mapping_resolution_status")
    if source_room_type_id and not mapping.get("room_type_id"):
        if "source_room_type_id_present" not in risk_flags:
            risk_flags.append("source_room_type_id_present")
        if source_has_product:
            source_mapping_status = "mapped"
    row.update(
        {
            "hotel_id": row.get("hotel_id") or requested_hotel_id,
            "tenant_filter_mode": hotel_scope.get("tenant_filter_mode"),
            "mapping_id": mapping.get("mapping_id"),
            "mapping_status": mapping.get("mapping_status"),
            "match_rule": mapping.get("match_rule"),
            "mapping_resolution_status": source_mapping_status if hotel_scope.get("mapping_resolution_status") != "data_gap" else "data_gap",
            "mapping_active": bool(mapping.get("mapping_active") or (source_room_type_id and source_has_product)),
            "room_type_id": mapping.get("room_type_id") or source_room_type_id,
            "room_type_name": mapping.get("room_type_name") or _value(row, "room_type_name", "pms_room_type_name"),
            "risk_flags": risk_flags,
            "business_date": _value(row, "business_date", "date", "stat_date"),
            "data_snapshot_time": _value(row, "data_snapshot_time", "snapshot_time", "updated_at", "created_at"),
            "freshness_status": "fresh" if _value(row, "business_date", "snapshot_time", "updated_at", "created_at") else "not_available",
        }
    )
    for key in ("source_room_type_id", "source_product_id", "source_product_name"):
        if row.get(key) is None and mapping.get(key) is not None:
            row[key] = mapping.get(key)
    for key in ("price_editable_flag", "is_hour_room"):
        if row.get(key) is None and mapping.get(key) is not None:
            row[key] = mapping.get(key)
    if mapping.get("product_cipher") is not None:
        row["product_cipher"] = mapping.get("product_cipher")
    return row


def normalize_ota_price_row(
    raw_row: dict[str, Any],
    mapping_index: dict[str, Any],
    *,
    requested_hotel_id: str | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _normalized_base_row(raw_row, mapping_index, requested_hotel_id, profile or {})


def normalize_room_metric_row(
    raw_row: dict[str, Any],
    mapping_index: dict[str, Any],
    *,
    requested_hotel_id: str | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _normalized_base_row(raw_row, mapping_index, requested_hotel_id, profile or {})


def normalize_rows_for_template(
    template: str,
    rows: list[dict[str, Any]],
    mapping_index: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    profile = profile or {}
    requested_hotel_id = profile.get("hotel_id")
    normalizer = normalize_ota_price_row if template in {"ota_price_mapping", "price_task_queue", "price_snapshot"} else normalize_room_metric_row
    return [normalizer(row, mapping_index, requested_hotel_id=requested_hotel_id, profile=profile) for row in rows]


def is_price_task_mapping_ready(row: dict[str, Any], *, disabled_platforms: set[str] | None = None) -> dict[str, Any]:
    platform = normalize_source_platform(_value(row, "source_platform", "channel_source", "platform"))
    source_product_id = _value(row, "source_product_id", "ota_product_id")
    status = str(_value(row, "mapping_status") or "").strip().upper()
    active = _truthy(_value(row, "mapping_active", "is_active", "active"))
    resolution = str(_value(row, "mapping_resolution_status") or "").strip().lower()
    raw_risks = row.get("mapping_risk_flags")
    if raw_risks in (None, ""):
        raw_risks = row.get("risk_flags")
    if isinstance(raw_risks, str):
        mapping_risks = {item.strip() for item in raw_risks.split(",") if item.strip()}
    elif isinstance(raw_risks, (list, tuple, set)):
        mapping_risks = {str(item).strip() for item in raw_risks if str(item).strip()}
    else:
        mapping_risks = set()

    disabled = disabled_platforms or DISABLED_PRICE_TASK_PLATFORMS
    blocking_mapping_risks = {
        "mapping_conflict",
        "mapping_candidate_name_match",
        "inferred_by_name",
        "tenant_scope_mismatch",
        "tenant_scope_unresolved",
    }
    risks: list[str] = []
    blocked_reason: str | None = None
    if not is_trusted_price_mapping(row):
        risks.append("price_task_blocked")
        blocked_reason = "mapping_not_trusted"
    elif resolution and resolution != "mapped":
        risks.append("price_task_blocked")
        blocked_reason = "mapping_not_exact"
    elif mapping_risks & blocking_mapping_risks:
        risks.append("price_task_blocked")
        blocked_reason = "mapping_not_exact"
    elif not active:
        risks.append("price_task_blocked")
        blocked_reason = "mapping_inactive"
    elif not _value(row, "room_type_id", "pms_room_type_id"):
        risks.append("price_task_blocked")
        blocked_reason = "room_type_id_missing"
    elif not source_product_id:
        risks.append("price_task_blocked")
        blocked_reason = "source_product_id_missing"
    elif platform in disabled:
        risks.append("price_task_blocked")
        blocked_reason = "source_platform_disabled"
    elif platform == "ctrip" and not _value(row, "product_cipher"):
        risks.append("price_task_blocked")
        blocked_reason = "ctrip_product_cipher_missing"
    return {
        "ready_for_price_task": blocked_reason is None,
        "blocked_reason": blocked_reason,
        "mapping_trust_basis": price_task_mapping_trust_basis(row),
        "mapping_resolution_status": (
            "mapped"
            if blocked_reason is None
            else (
                "mapping_inactive"
                if blocked_reason == "mapping_inactive"
                else "mapping_pending"
            )
        ),
        "risk_flags": risks,
    }
