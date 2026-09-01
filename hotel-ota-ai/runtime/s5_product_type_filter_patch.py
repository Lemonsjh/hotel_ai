from __future__ import annotations

import sys
from typing import Any, Mapping


_INSTALLED = False
VERSION = "s5-product-type-filter.v3"
_CLASSIFICATION_FIELDS = (
    "is_hour_room",
    "rate_plan_name",
    "is_super_deal",
    "ota_product_name",
)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) == 1.0
    return str(value or "").strip().lower() in {
        "1",
        "1.0",
        "true",
        "yes",
        "y",
    }


def _product_id(row: Mapping[str, Any]) -> str:
    return str(row.get("ota_product_id") or row.get("source_product_id") or "").strip()


def _channel(row: Mapping[str, Any]) -> str:
    channel = str(
        row.get("channel")
        or row.get("source_platform")
        or row.get("channel_source")
        or ""
    ).strip().lower()
    if channel:
        return channel
    table_key = str(row.get("table_key") or row.get("source_table_key") or "").lower()
    if table_key.startswith("meituan"):
        return "meituan"
    if table_key.startswith("ctrip"):
        return "ctrip"
    return ""


def _classification_source(
    row: Mapping[str, Any],
    raw_rows: list[Any],
) -> Mapping[str, Any] | None:
    product_id = _product_id(row)
    if not product_id:
        return None
    channel = _channel(row)
    exact: list[Mapping[str, Any]] = []
    same_product: list[Mapping[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping) or _product_id(raw) != product_id:
            continue
        same_product.append(raw)
        if channel and _channel(raw) == channel:
            exact.append(raw)
    if len(exact) == 1:
        return exact[0]
    if len(same_product) == 1:
        return same_product[0]
    return None


def _classification_row(
    row: Mapping[str, Any],
    raw_rows: list[Any],
) -> dict[str, Any]:
    """Recover only classification facts lost by the price_snapshots projection."""

    classified = dict(row)
    source = _classification_source(row, raw_rows)
    if source is None:
        return classified
    for field in _CLASSIFICATION_FIELDS:
        if classified.get(field) in (None, "") and source.get(field) not in (None, ""):
            classified[field] = source.get(field)
    return classified


def unsupported_product_type(row: Mapping[str, Any]) -> str | None:
    """Return the S5-excluded OTA product type, if any.

    Hour-room classification follows the Meituan mapping facts in priority order:
    1. explicit is_hour_room truthy flag;
    2. rate_plan_name exactly equals 标准价;
    3. ota_product_name explicitly contains 钟点房 or 小时房.

    meituan_ota_goods_price_mapping does not provide product_type, so S5 must not
    use product_type as a classification source.
    """

    if _truthy(row.get("is_hour_room")):
        return "hour_room"

    rate_plan_name = str(row.get("rate_plan_name") or "").strip()
    if rate_plan_name == "标准价":
        return "hour_room"

    product_name = str(row.get("ota_product_name") or "").strip().lower()
    if any(token in product_name for token in ("钟点房", "小时房")):
        return "hour_room"

    if _truthy(row.get("is_super_deal")):
        return "super_deal"
    if any(token in product_name for token in ("超级团购", "super deal")):
        return "super_deal"
    return None


def filter_ota_price_mapping_result(
    result: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Remove unsupported rows before S5 recommendation calculation."""

    copied = dict(result)
    payload_value = copied.get("payload")
    if not isinstance(payload_value, Mapping):
        return copied, []

    payload = dict(payload_value)
    raw_rows_value = payload.get("rows")
    raw_rows = raw_rows_value if isinstance(raw_rows_value, list) else []
    rows_key = None
    rows: list[Any] | None = None
    for candidate_key in ("price_snapshots", "rows"):
        candidate_rows = payload.get(candidate_key)
        if isinstance(candidate_rows, list):
            rows_key = candidate_key
            rows = candidate_rows
            break
    if rows_key is None or rows is None:
        copied["payload"] = payload
        return copied, []

    kept: list[Any] = []
    excluded_types: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            kept.append(row)
            continue
        classified = _classification_row(row, raw_rows) if rows_key == "price_snapshots" else dict(row)
        excluded_type = unsupported_product_type(classified)
        if excluded_type is None:
            kept.append(dict(row))
            continue
        excluded_types.append(excluded_type)

    payload[rows_key] = kept
    payload["s5_excluded_unsupported_product_count"] = len(excluded_types)
    payload["s5_excluded_unsupported_product_types"] = sorted(set(excluded_types))
    copied["payload"] = payload
    return copied, excluded_types


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.algorithms import s5_real_candidates as s5_module

    previous_build = s5_module.build_s5_real_candidates
    if not getattr(previous_build, "_S5_PRODUCT_TYPE_FILTER_V3", False):

        def build_s5_real_candidates(*args: Any, **kwargs: Any) -> dict[str, Any]:
            original_query = kwargs.get("query")
            if not callable(original_query):
                return previous_build(*args, **kwargs)

            excluded_types: list[str] = []

            def filtered_query(
                template: str,
                hotel_id: str,
                **query_kwargs: Any,
            ) -> dict[str, Any]:
                query_result = original_query(template, hotel_id, **query_kwargs)
                if template != "ota_price_mapping" or not isinstance(query_result, Mapping):
                    return query_result
                filtered, excluded = filter_ota_price_mapping_result(query_result)
                excluded_types.extend(excluded)
                return filtered

            patched_kwargs = dict(kwargs)
            patched_kwargs["query"] = filtered_query
            result = dict(previous_build(*args, **patched_kwargs))

            excluded_count = len(excluded_types)
            excluded_unique = sorted(set(excluded_types))
            result.update(
                {
                    "s5_product_type_filter_version": VERSION,
                    "excluded_unsupported_product_count": excluded_count,
                    "excluded_unsupported_product_types": excluded_unique,
                }
            )
            if excluded_count:
                quality_flags = [str(item) for item in (result.get("quality_flags") or [])]
                for excluded_type in excluded_unique:
                    flag = f"excluded_unsupported_product_type:{excluded_type}"
                    if flag not in quality_flags:
                        quality_flags.append(flag)
                result["quality_flags"] = quality_flags
                if kwargs.get("ota_product_id") and not (result.get("candidates") or []):
                    result["requested_product_excluded_reason"] = "unsupported_price_product_type"
            return result

        build_s5_real_candidates._S5_PRODUCT_TYPE_FILTER_V3 = True  # type: ignore[attr-defined]
        s5_module.build_s5_real_candidates = build_s5_real_candidates

        router = sys.modules.get("runtime.feishu_command_router")
        if router is not None and hasattr(router, "build_s5_real_candidates"):
            router.build_s5_real_candidates = build_s5_real_candidates

    # Keep the production change minimal: this patch is already installed from
    # runtime.__init__, so activate the existing S5 no-sellable-inventory filter
    # here instead of changing S6 or duplicating inventory logic.
    from runtime.s5_room_inventory_filter_patch import install as install_room_inventory_filter

    install_room_inventory_filter()

    # Net-revenue activity evidence is independent across summary/detail tables.
    # Install the latency-only query patch from the same production S5 bootstrap.
    from runtime.s5_activity_query_parallel_patch import install as install_activity_query_parallel

    install_activity_query_parallel()
