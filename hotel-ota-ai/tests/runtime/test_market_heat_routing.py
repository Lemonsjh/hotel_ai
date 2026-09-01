from runtime.feishu_command_router import _detect_intent


def test_current_market_heat_routes_to_s16() -> None:
    message = "\u5927\u76d8\u70ed\u5ea6\u662f\u591a\u5c11"
    assert _detect_intent(message) == "progress_deviation_demo"
