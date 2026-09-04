from __future__ import annotations

import json
from datetime import datetime

import pytest

from runtime import feishu_command_router as router
from runtime import skill_orchestrator
from runtime.decisions import command_menu


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("今天经营怎么样", "run_s02"),
        ("今天经营情况", "run_s02"),
        ("当前出租率", "run_s02"),
        ("今日日报", "run_s02"),
        ("生成今日日报", "run_s02"),
        ("请生成一份今日经营日报", "run_s02"),
        ("昨日日报", "run_s02"),
        ("生成昨日日报", "run_s02"),
        ("请生成一份昨日经营日报", "run_s02"),
        ("生成昨日日报，包含销售进度、流量转化和健康度", "run_s02"),
        ("生成今日日报，做综合分析", "run_s02"),
        ("大盘冷不冷", "market_context_demo"),
        ("今天市场怎么样", "market_context_demo"),
        ("今天要不要调价", "revenue_decision"),
        ("是否需要调价", "revenue_decision"),
        ("今天要不要调价，大盘怎么样", "revenue_decision"),
        ("为什么销售落后", "progress_deviation_demo"),
        ("为什么今天卖得慢", "progress_deviation_demo"),
        ("今天流量怎么样", "progress_deviation_demo"),
        ("浏览怎么样", "progress_deviation_demo"),
        ("一转怎么样", "progress_deviation_demo"),
        ("二转怎么样", "progress_deviation_demo"),
        ("销售进度怎么样", "progress_deviation_demo"),
        ("销售基准线", "sales_baseline_demo"),
    ],
)
def test_p0_natural_language_route_ownership(message: str, expected: str) -> None:
    assert router._detect_intent(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "5",
        "s14",
        "S14诊断",
        "OTA运营诊断",
        "综合运营诊断",
        "综合诊断",
        "完整经营分析",
        "昨日复盘",
        "近7天诊断",
        "近30天诊断",
        "自然月诊断",
    ],
)
def test_s14_main_routes_are_retired(message: str) -> None:
    assert router._detect_intent(message) == "s14_retired"


def test_daily_report_date_scope_is_owned_by_report_phrase() -> None:
    yesterday = router.resolve_request_as_of_time(
        "生成昨日日报",
        now=datetime(2026, 8, 7, 14, 16, 0),
    )
    assert yesterday["target_business_date"] == "2026-08-06"
    assert yesterday["as_of_time_source"] == "message_explicit"

    today = router.resolve_request_as_of_time(
        "生成今日日报，对比昨日",
        now=datetime(2026, 8, 7, 14, 16, 0),
    )
    assert today["target_business_date"] == "2026-08-07"


def test_daily_report_explicit_clock_is_preserved() -> None:
    context = router.resolve_request_as_of_time(
        "生成昨日经营日报，截至18:30",
        now=datetime(2026, 8, 7, 20, 0, 0),
    )
    assert context["target_business_date"] == "2026-08-06"
    assert context["as_of_time"] == "2026-08-06 18:30:00"


def test_s14_ext_source_keeps_independent_service_boundary() -> None:
    assert router._detect_intent("s14 source=monthly_excel") == "s14_source_request"
    result = router.safe_route_feishu_command(
        "s14 source=monthly_excel",
        render=False,
        compact=False,
    )
    assert result["status"] == "data_gap"
    assert result["blocked_reason"] == "s14_ext_migrated_to_independent_service"
    assert result["business_result_generated"] is False
    assert result.get("skill_id") is None


def test_s14_exact_request_reports_group_bot_unconfigured(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv(
        "HOTEL_OTA_DIAGNOSIS_BOT_CONFIG",
        str(tmp_path / "missing-diagnosis-bot-map.json"),
    )
    result = router.safe_route_feishu_command(
        "综合诊断",
        chat_id="chat:oc_group_a",
        render=False,
        compact=False,
    )
    assert result["status"] == "blocked"
    assert result["intent"] == "s14_retired"
    assert result["blocked_reason"] == "s14_retired_from_production_feishu"
    assert result["business_result_generated"] is False
    assert result["diagnosis_bot_configured"] is False
    assert "当前群未配置独立综合诊断机器人" in result["summary"]
    assert result.get("skill_id") is None
    assert result.get("runtime_command") is None


def test_s14_exact_request_hands_off_to_exact_group_bot(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    config_path = tmp_path / "diagnosis-bot-map.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "group_chat_bots": [
                    {
                        "chat_id": "oc_group_a",
                        "bot_name": "酒店综合诊断二号",
                        "status": "active",
                    },
                    {
                        "chat_id": "oc_group_b",
                        "bot_name": "其他群诊断机器人",
                        "status": "active",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOTEL_OTA_DIAGNOSIS_BOT_CONFIG", str(config_path))

    result = router.safe_route_feishu_command(
        "s14",
        chat_id="chat:oc_group_a",
        render=False,
        compact=False,
    )
    assert result["diagnosis_bot_configured"] is True
    assert result["diagnosis_bot_name"] == "酒店综合诊断二号"
    assert "请在群内 @酒店综合诊断二号" in result["summary"]
    assert "其他群诊断机器人" not in result["summary"]


def test_menu_slot_five_is_removed_from_all_runtime_menu_sources() -> None:
    assert "5" not in router.NUMERIC_MENU_INTENTS
    assert "5" not in command_menu.COMMAND_BY_ID
    assert "5" not in command_menu.COMMAND_V27_METADATA
    assert all(command.command_id != "5" for command in command_menu.COMMANDS)


def test_authoritative_menu_has_no_s14_item() -> None:
    result = router.safe_route_feishu_command("菜单", render=False, compact=False)
    text = str(result.get("summary") or "")
    assert result["status"] == "ok"
    assert result["intent"] == "menu"
    assert "5｜OTA" not in text
    assert "OTA 运营诊断" not in text
    assert "6｜竞对监控" in text
    assert "11｜推广数据" in text
    assert "13｜流量转化专项" in text


def test_s14_orchestrator_target_is_blocked_before_runner() -> None:
    called = False

    def runner(skill: str, hotel_id: str, context: dict[str, object]) -> dict[str, object]:
        nonlocal called
        called = True
        return {"status": "ok"}

    result = skill_orchestrator.run_skill_with_dependencies(
        target_skill="S14_OPERATION_DIAGNOSIS",
        hotel_id="hotel-test",
        runner=runner,
    )
    assert result["blocked"] is True
    assert result["blocked_reason"] == "s14_retired_from_production_feishu"
    assert called is False


def test_s14_retirement_and_daily_report_route_are_both_installed() -> None:
    assert getattr(router._detect_intent, "_S14_PRODUCTION_RETIRED_V1", False) is True
    assert getattr(router._detect_intent, "_S2_DAILY_REPORT_ROUTE_V1", False) is True
    assert getattr(router.safe_route_feishu_command, "_S14_PRODUCTION_RETIRED_V1", False) is True
