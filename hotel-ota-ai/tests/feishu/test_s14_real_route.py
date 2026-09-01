from runtime.feishu_command_router import (
    DEMO_FALLBACK_INTENTS,
    PROTECTED_BUSINESS_INTENTS,
    _detect_intent,
)
from runtime.s14_bundle_builder import is_s14_operation_message


def test_real_s14_intent_is_not_a_demo_fallback() -> None:
    assert _detect_intent("本店 OTA运营诊断") == "operation_diagnosis"
    assert _detect_intent("本店 OTA运营诊断 演示") == "ota_diagnosis_demo"
    assert "operation_diagnosis" in PROTECTED_BUSINESS_INTENTS
    assert "operation_diagnosis" not in DEMO_FALLBACK_INTENTS
    assert is_s14_operation_message("本店 OTA运营诊断")
