from __future__ import annotations

from pathlib import Path

from runtime.s17_feishu_route_patch import _finish_result, _strip_demo_scaffold_metadata
from runtime.s17_guest_frequency_patch import (
    _bulk_guest_frequency_min_visits,
    _bulk_guest_frequency_summary,
)
from runtime.s17_public_text_patch import enrich_s17_public_summary
from runtime.safety.feishu_output import feishu_output_gate


def _payload() -> dict[str, object]:
    return {
        "window_start": "2026-07-11 20:11:00",
        "window_end": "2026-08-10 20:11:00",
        "as_of_datetime": "2026-08-10 20:11:00",
        "privacy_policy": {
            "minimum_cohort_size": 5,
            "hotel_operational_aggregate_small_cell_suppression": False,
            "person_or_profile_cohort_small_cell_suppression": True,
        },
        "source_status": {
            "booking": {"status": "ok"},
            "realized": {"status": "ok"},
            "extension": {"status": "ok"},
            "real_guest_frequency_realized": {"status": "ok"},
            "real_guest_frequency_contact_corroboration": {"status": "ok"},
        },
        "populations": {
            "pms_booking_created": {
                "unmapped_count": 0,
                "suppressed_booking_matrix_cell_count": 0,
                "booking_matrix": [
                    {
                        "booking_channel": "meituan",
                        "guest_source_class": "中介",
                        "room_type_name": "至臻・电竞大床房",
                        "created_order_count": 3,
                        "booked_rooms": 4,
                        "active_order_count": 2,
                        "active_booked_rooms": 3,
                    }
                ],
                "contact_proxy": {
                    "status": "ok",
                    "eligible_contact_keys": 10,
                    "repeat_contact_keys": 2,
                    "contact_seen_before_share_proxy": 0.3,
                    "repeat_booking_contact_share_proxy": 0.2,
                    "repeat_booking_order_share_proxy": 0.15,
                    "repeat_stayed_contact_share_proxy": 0.1,
                    "suppressed_contact_frequency_cell_count": 1,
                },
            },
            "pms_arrival_cohort": {
                "unmapped_count": 0,
                "suppressed_room_type_room_distribution_cell_count": 0,
            },
            "realized_stay": {
                "unmapped_count": 0,
                "suppressed_room_type_distribution_cell_count": 0,
            },
            "real_guest_frequency": {
                "status": "ok",
                "valid_guest_name_count": 12,
                "realized_frequency_guest_name_count": 12,
                "suppressed_frequency_distribution_cell_count": 0,
            },
            "extension_reconciliation": {
                "unmapped_count": 0,
                "suppressed_room_type_distribution_cell_count": 0,
            },
            "meituan_scan_order": {
                "total_orders": 6,
                "cells": [
                    {"bucket": "provider_new", "order_count": 4},
                    {"bucket": "provider_returning", "order_count": 2},
                ],
            },
            "meituan_loss": {
                "status": "ok",
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "provider_loss_orders": 5,
                "provider_loss_room_nights": 6,
                "provider_loss_amount": 880,
            },
        },
    }


class _FakeRouter:
    @staticmethod
    def render_feishu_output(result, output_profile):
        return {
            "status": "ok",
            "output_profile": output_profile or "owner_business",
            "text": "generic renderer text",
            "template": "business_snapshot",
        }

    @staticmethod
    def build_feishu_send_payload(result, role=None):
        return {
            "text": "generic send text",
            "send_allowed": True,
            "warnings": [],
            "output_profile": "owner_business",
        }

    @staticmethod
    def compact_feishu_route_result(result):
        return result


def test_repeat_guest_requests_route_to_named_frequency_with_two_visit_floor() -> None:
    for text in (
        "客户到店次数分析",
        "2次以上人的名字",
        "列出2次及以上客户姓名",
        "统计到店次数2次以上的客户",
        "统计到店次数2次及以上客户",
        "回头客有哪些",
        "重复入住的客户有哪些",
        "再次到店的客人有哪些",
        "来过不止一次的住客有哪些",
        "复购客户有哪些",
    ):
        assert _bulk_guest_frequency_min_visits(text) == 2, text


def test_all_guest_frequency_request_uses_one_visit_floor() -> None:
    for text in (
        "每个客户到店的次数有多少",
        "每位客户到店次数",
        "各客户到店次数",
        "客户分别来了几次",
        "客户到店次数明细",
    ):
        assert _bulk_guest_frequency_min_visits(text) == 1, text


def test_high_frequency_guest_requests_use_three_visit_floor() -> None:
    for text in (
        "高频到店客户有哪些",
        "高频到店的客户有哪些？",
        "高频的客户有哪些",
        "给我展示高频到店客户姓名",
        "经常到店的客户有哪些",
        "经常来的客户有哪些",
        "常来客户有哪些",
        "常客有哪些",
    ):
        assert _bulk_guest_frequency_min_visits(text) == 3, text


def test_explicit_guest_frequency_thresholds_preserve_chinese_comparison_semantics() -> None:
    assert _bulk_guest_frequency_min_visits("3次以上的有哪些") == 3
    assert _bulk_guest_frequency_min_visits("至少3次的客户有哪些") == 3
    assert _bulk_guest_frequency_min_visits("不少于三次的住客有哪些") == 3
    assert _bulk_guest_frequency_min_visits("超过2次的客户有哪些") == 3
    assert _bulk_guest_frequency_min_visits("多于3次的客人有哪些") == 4


def test_bulk_guest_frequency_summary_answers_only_requested_scope() -> None:
    payload = _payload()
    populations = payload["populations"]
    assert isinstance(populations, dict)
    frequency = populations["real_guest_frequency"]
    assert isinstance(frequency, dict)
    frequency["guest_name_visit_counts"] = [
        {"guest_name": "张丽芳", "visit_count": 7},
        {"guest_name": "郝玉超", "visit_count": 6},
        {"guest_name": "刘庚", "visit_count": 3},
        {"guest_name": "令狐凯旋", "visit_count": 2},
        {"guest_name": "丁林", "visit_count": 1},
    ]

    text = _bulk_guest_frequency_summary(payload, 2)

    assert text is not None
    assert "S17 客户到店次数（2026-07-11 至 2026-08-10）" in text
    assert "到店 2 次及以上客户共 4 位" in text
    assert "张丽芳：7 次" in text
    assert "令狐凯旋：2 次" in text
    assert "丁林" not in text
    for unrelated in (
        "订单总览",
        "预订房型",
        "预订渠道 × 客源 × 房型矩阵",
        "联系人新旧与复购代理",
        "平台增强背景",
        "口径与质量",
    ):
        assert unrelated not in text


def test_real_s17_strips_demo_scaffold_metadata() -> None:
    result = {
        "status": "ok",
        "intent": "customer_analysis",
        "summary": "真实数据库 S17",
        "data_source_type": "real_database",
        "demo_dataset_id": "demo-v1",
        "demo_business_date": "2026-06-11",
        "data_business_date": "2026-06-11",
        "business_date": "2026-06-11",
        "freshness_status": "demo_data",
        "business_status": "demo_or_historical",
        "hotel_name": "Demo Hotel",
    }

    _strip_demo_scaffold_metadata(result)

    for key in (
        "demo_dataset_id",
        "demo_business_date",
        "data_business_date",
        "business_date",
        "freshness_status",
        "business_status",
        "hotel_name",
    ):
        assert key not in result
    assert result["data_source_type"] == "real_database"
    assert result["summary"] == "真实数据库 S17"


def test_hotel_business_text_is_not_authorized_by_keyword_gate() -> None:
    for text in (
        "窗口内到店 3 次及以上客户（2 位）：\n- 张三：5 次\n- 李四：3 次",
        "客户名单：张三、李四",
        "住客名单：张三、李四",
        "住客张三，房号301",
        "订单明细：订单A，房号301",
        "逐条订单：订单A、订单B",
    ):
        result = feishu_output_gate(message=text)
        assert result["status"] == "ok", (text, result)
        assert result["blocked_reason"] is None


def test_system_secret_still_fails_final_output_gate() -> None:
    blocked = feishu_output_gate(message="mysql://hotel:secret@example.internal/db")
    assert blocked["status"] == "blocked"
    assert blocked["blocked_reason"] == "config_or_secret_export_not_allowed"


def test_s17_final_send_payload_is_verbatim_and_uses_runtime_summary() -> None:
    summary = "窗口内到店 3 次及以上客户（2 位）：\n- 张三：5 次\n- 李四：3 次"
    result = {
        "status": "ok",
        "intent": "customer_analysis",
        "summary": summary,
        "output_profile": "owner_business",
    }
    finished = _finish_result(
        _FakeRouter(),
        result,
        render=True,
        compact=False,
        role="owner",
    )
    send_payload = finished["send_payload"]
    assert send_payload["send_allowed"] is True
    assert send_payload["text"] == summary
    assert send_payload["delivery_mode"] == "verbatim"
    assert send_payload["model_rewrite_allowed"] is False
    assert send_payload["content_source"] == "runtime_deterministic_s17"
    assert finished["rendered"]["text"] == summary


def test_complete_s17_public_summary_adds_missing_contract_sections_without_row_details() -> None:
    text = enrich_s17_public_summary(
        "S17 客户与订单结构分析\n订单总览：3 单。\n边界：各口径不得相加。",
        _payload(),
    )
    assert "预订渠道 × 客源 × 房型矩阵：" in text
    assert "美团 / 中介 / 至臻・电竞大床房：3 单、4 间预订房" in text
    assert "联系人新旧与复购代理（预订联系人，不代表实际入住人）：" in text
    assert "平台增强背景（可用时展示，均不与 PMS 核心口径相加）：" in text
    assert "口径与质量：" in text
    assert "住客频次住宿事实可用" in text
    assert "酒店级经营聚合不按个人小样本阈值隐藏" in text
    assert "统一房型未映射" not in text
    for forbidden in ("order_id", "room_no", "HMAC", "电话号码"):
        assert forbidden not in text


def test_s17_public_summary_only_reports_positive_unmapped_counts() -> None:
    payload = _payload()
    populations = payload["populations"]
    assert isinstance(populations, dict)
    realized = populations["realized_stay"]
    assert isinstance(realized, dict)
    realized["unmapped_count"] = 2

    text = enrich_s17_public_summary(
        "S17 客户与订单结构分析\n订单总览：3 单。\n边界：各口径不得相加。",
        payload,
    )

    assert "统一房型未映射：实际入住 2" in text
    assert "预订 0" not in text
    assert "计划到店 0" not in text
    assert "续住 0" not in text


def test_s17_rules_no_longer_reintroduce_content_keyword_privacy_gate() -> None:
    root = Path(__file__).resolve().parents[2]
    rules = (
        root
        / "skills"
        / "hotel-ota"
        / "s17-customer-order-analysis"
        / "references"
        / "rules.md"
    ).read_text(encoding="utf-8")
    assert "禁止批量姓名名单" not in rules
    assert "只有用户明确查询单一姓名" not in rules
    assert "泛化客户名单、住客名单、订单明细、逐条住宿记录仍必须由统一飞书输出门禁阻断" not in rules
    assert "S17 不再读取或输出 KF11 当前物理在住" in rules
    assert "`charge_subject` 是收入分类，不是住客是否到店的判断条件" in rules
    assert "`客户到店次数分析` 固定解释为“重复到店核查”" in rules
    assert "`高频到店客户有哪些`、`展示高频到店客户姓名`" in rules
    assert "业务字段是否可见由生产鉴权、exact hotel scope 和能力权限决定" in rules
