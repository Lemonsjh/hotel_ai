from __future__ import annotations

from typing import Any, Mapping

_INSTALLED = False
VERSION = "s16-skill-delivery.v8"
KNOWLEDGE_FILE = (
    "skills/hotel-ota/s16-progress-deviation/"
    "S16_RUNTIME_KNOWLEDGE_INDEX.md"
)
KNOWLEDGE_FILES = [
    KNOWLEDGE_FILE,
    (
        "skills/hotel-ota/s16-progress-deviation/"
        "S16_MEITUAN_DAILY_PROJECTION_AND_ADVISORY_RULES.md"
    ),
    (
        "skills/hotel-ota/s16-progress-deviation/"
        "MEITUAN_ACTIVITY_NET_PRICE_RULES.md"
    ),
    (
        "skills/hotel-ota/s16-progress-deviation/"
        "S16_DYNAMIC_DIAGNOSIS_KNOWLEDGE.md"
    ),
]

_STATUS_LABELS = {
    "severe_slow": "严重偏慢",
    "significant_slow": "明显偏慢",
    "slow": "偏慢",
    "normal": "正常",
    "fast": "偏快",
    "significant_fast": "明显偏快",
    "sample_insufficient": "样本不足",
    "unavailable": "暂不可判断",
}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num(value: Any, digits: int = 1) -> str:
    number = _number(value)
    if number is None:
        return "—"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _pp(value: Any) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:+.1f}个百分点"


def _status_text(value: Any) -> str:
    return _STATUS_LABELS.get(str(value or ""), str(value or "暂不可判断"))


def _room_rows(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    dynamic = result.get("dynamic_diagnosis") or {}
    rows = (
        (dynamic.get("room_structure") or {}).get("room_type_results") or []
    )
    if not rows:
        rows = result.get("room_type_results") or []
    return [row for row in rows if isinstance(row, Mapping)]


def render_complete_room_structure(result: Mapping[str, Any]) -> str:
    """Render the complete deterministic S16 room-structure block.

    This block intentionally preserves every room returned by room_type_results.
    Normal, zero-sold and sample-insufficient rooms are facts too; they must not
    be filtered or top-N truncated before the Feishu/AI delivery boundary.
    """

    rows = _room_rows(result)
    lines = ["三、房型结构"]
    if not rows:
        lines.append("- 当前没有可展示的房型进度事实。")
        return "\n".join(lines)

    for row in rows:
        name = row.get("room_type_name") or row.get("room_type_id") or "未知房型"
        lines.append(
            f"- {name}：已售 {_num(row.get('committed_sold'))}/"
            f"{_num(row.get('total_rooms'))}间，当前应售 "
            f"{_num(row.get('current_expected_sold'))}间，相差 "
            f"{_num(row.get('checkpoint_room_gap'))}间，进度偏差 "
            f"{_pp(row.get('sales_progress_delta_pp'))}，"
            f"{_status_text(row.get('sales_status'))}。"
        )
    return "\n".join(lines)


def _replace_room_structure_section(
    text: str,
    result: Mapping[str, Any],
) -> str:
    """Replace any filtered S16 room section with the complete fact block."""

    if not _room_rows(result):
        return text
    block = render_complete_room_structure(result)
    lines = str(text or "").splitlines()

    try:
        start = lines.index("三、房型结构")
    except ValueError:
        try:
            reason_index = lines.index("四、原因判断")
        except ValueError:
            return (str(text or "").rstrip() + "\n\n" + block).strip()
        return "\n".join(
            lines[:reason_index] + block.splitlines() + [""] + lines[reason_index:]
        )

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index] == "四、原因判断":
            end = index
            break
    replacement = block.splitlines()
    if end < len(lines):
        replacement.append("")
    return "\n".join(lines[:start] + replacement + lines[end:])


def _patch_complete_room_structure() -> None:
    from runtime import (
        s15_s16_complete_output_patch,
        s15_s16_responsibility_patch,
    )
    from runtime.sales_progress import presentation

    previous = s15_s16_responsibility_patch._dynamic_message
    if getattr(previous, "_S16_COMPLETE_ROOM_STRUCTURE_V7", False):
        return

    def complete_message(result: Mapping[str, Any]) -> str:
        return _replace_room_structure_section(previous(result), result)

    complete_message._S16_COMPLETE_ROOM_STRUCTURE_V7 = True  # type: ignore[attr-defined]
    s15_s16_responsibility_patch._dynamic_message = complete_message
    presentation.build_s16_user_message = complete_message
    s15_s16_complete_output_patch.s16_message = complete_message


def build_s16_response_contract(result: Mapping[str, Any]) -> dict[str, Any]:
    dynamic = result.get("dynamic_diagnosis") or {}
    room_rows = _room_rows(result)
    all_room_ids = [
        str(row.get("room_type_id"))
        for row in room_rows
        if row.get("room_type_id")
    ]
    anomalous_room_ids = [
        str(row.get("room_type_id"))
        for row in room_rows
        if row.get("room_type_id")
        and str(row.get("sales_status") or "normal") != "normal"
    ]
    advisory_product_ids = [
        str(row.get("ota_product_id"))
        for row in dynamic.get("estimated_price_advisories") or []
        if row.get("ota_product_id")
    ]
    locked_room_structure_text = render_complete_room_structure(result)
    return {
        "mode": "single_pass_skill_guided_business_analysis",
        "knowledge_file": KNOWLEDGE_FILE,
        "knowledge_files": list(KNOWLEDGE_FILES),
        "knowledge_precedence": list(KNOWLEDGE_FILES),
        "facts_are_authoritative": True,
        "maximum_runtime_tool_calls": 1,
        "additional_database_queries_allowed": False,
        "second_analysis_pass_allowed": False,
        "routing_boundary": {
            "direct_pricing_question_owner": "S5",
            "s16_price_role": "在经营偏差诊断中解释价格是否可能是原因，不替代 S5 收益候选",
            "redirect_only_reply_allowed": False,
        },
        "available_section_order": [
            "当前结论",
            "销售进度",
            "房型结构",
            "原因判断",
            "建议动作",
            "数据限制",
        ],
        "section_selection_allowed": True,
        "must_preserve": [
            "所有引用的数字、日期、单位和酒店范围",
            "主要原因、次要原因及其确定性状态",
            "美团大盘估算和估算份额必须使用PAY_ORDER_CNT全字段优先；仅当PAY同字段为空时，才允许同业务日同snapshot_time的FLOW_PAY_ORDER_CNT补充metric_value、peer_average或该批次同行范围信息",
            "同行酒店总数允许使用同业务日同snapshot_time其它美团指标competitor_rank的共同分母补充；不得把其它指标的排名名次冒充PAY_ORDER_CNT排名",
            "S16当前大盘事实绝不跨业务日取数；当前批次不足时只能标记不可用，不能借上一日、历史日或其它批次补值",
            "美团小时采集时间及可能存在约一小时延迟",
            "美团浏览线性收盘估算以及一转二转当前累计率方向",
            "所有平台指标必须明确写明为美团口径",
            "美团底价先扣佣金再将全部有效活动系数连续相乘",
            "低置信试探涨降价的具体商品、幅度、观察期和只读边界",
            "影响结论的数据限制和统计周期边界",
            "商品价格是否具有同一商品可比历史",
            "动作尚未执行及对应下游能力边界",
            "房型结构一旦输出，必须逐个覆盖room_type_results中的全部房型，包括正常、零售出和样本不足房型；不得只保留异常房型",
            "房型结构必须原样保留locked_room_structure_text中的全部房型行，不得缩略、合并、排序后丢失或改写数字",
            "每个房型必须保留房型名、已售/总房、同时点应售、间数差、相对同时点基准的具体pp偏差和状态",
        ],
        "all_room_type_ids": all_room_ids,
        "room_type_count": len(all_room_ids),
        "must_preserve_all_room_types": True,
        "locked_room_structure_text": locked_room_structure_text,
        "locked_room_structure_must_preserve_verbatim": True,
        "anomalous_room_type_ids": anomalous_room_ids,
        "must_preserve_anomalous_room_types": True,
        "advisory_ota_product_ids": advisory_product_ids,
        "must_preserve_price_advisories": True,
        "allowed": [
            "按用户问题省略无关章节，但房型结构一旦输出必须保持完整房型集合",
            "用酒店经营中文解释确定性结果",
            "解释为什么建议或不建议动作",
            "解释当前趋势可能跑赢、接近或落后历史",
            "保持简洁并突出主要原因",
            "用户追问大盘口径时，可以解释PAY_ORDER_CNT优先以及同日同批次FLOW/其它指标仅用于补充缺失单元格",
            "在涉及价格时说明具体收益候选由 S5 负责，但仍须先回答已有的 S16 经营诊断结果",
        ],
        "forbidden": [
            "修改或重新计算事实、公式、阈值、佣金率、活动系数和建议幅度",
            "省略美团口径并把美团指标写成全渠道指标",
            "把本店美团支付订单称为代理值或改用JD01/PMS订单兜底",
            "在PAY_ORDER_CNT对应字段已有合法值时改用FLOW_PAY_ORDER_CNT覆盖它",
            "把同日同snapshot_time的FLOW_PAY_ORDER_CNT单字段补充描述成回退、兜底、降级或借用历史数据",
            "声称S16当前大盘可以使用上一业务日、昨天、历史日或不同snapshot_time的同行数据",
            "当前同批次关键字段不足时静默借用其它日期或其它批次，而不是明确标记当前大盘不可用",
            "把其它指标competitor_rank的排名名次当成PAY_ORDER_CNT排名；其它指标只允许提供共同的同行酒店总数分母",
            "把日内线性估算写成确定收盘结果或小时基准",
            "把不足样本表述为确定结论",
            "没有同一OTA商品历史时输出确定的价格偏高或偏低",
            "把低置信试探建议写成正式调价候选或已执行动作",
            "新增确定性代码未生成的动作候选",
            "省略会改变结论的数据限制",
            "房型结构只展示异常、偏快或偏慢房型而省略正常、零售出或样本不足房型",
            "缩减、合并或重排room_type_results导致事实包中的房型从房型结构章节消失",
            "改写或摘要locked_room_structure_text中的任一房型行",
            "已有具体pp偏差时只输出偏快、偏慢或正常标签而省略pp数值",
            "输出内部枚举、字段名、补丁版本或调试链路",
            "声称调价、推广、审批或任务已经执行",
            "只回复‘这是S5范围’、‘请改问S5’或其他转交话术而不回答已经取得的S16经营事实",
            "要求用户重新改写问题后才提供已有的经营偏差诊断",
        ],
        "fallback": "无法完整遵守约束时，原样发送 authoritative_fallback_text。",
        "contract_version": VERSION,
    }


def apply_s16_delivery_contract(
    result: Mapping[str, Any],
    rendered: Mapping[str, Any],
    send_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    rendered_result = dict(rendered)
    send_result = dict(send_payload)
    if str(result.get("intent") or "") != "progress_deviation_demo":
        return rendered_result, send_result

    text = _replace_room_structure_section(
        str(send_result.get("text") or rendered_result.get("text") or ""),
        result,
    )
    contract = build_s16_response_contract(result)
    if rendered_result.get("text") is not None:
        rendered_result["text"] = text
    send_result["text"] = text
    rendered_result.update(
        {
            "ai_analysis_allowed": True,
            "ai_rewrite_allowed": True,
            "must_send_text_verbatim": False,
            "assistant_response_contract_version": VERSION,
        }
    )
    send_result.update(
        {
            "ai_analysis_allowed": True,
            "ai_rewrite_allowed": True,
            "must_send_text_verbatim": False,
            "assistant_response_contract": contract,
            "authoritative_fallback_text": text,
        }
    )
    return rendered_result, send_result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s15_s16_runtime_patch

    _patch_complete_room_structure()

    previous = s15_s16_runtime_patch._direct_delivery
    if getattr(previous, "_S16_SKILL_DELIVERY_V7", False):
        return

    def direct_delivery(
        result: dict[str, Any],
        role: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        rendered, send_payload = previous(result, role)
        return apply_s16_delivery_contract(result, rendered, send_payload)

    direct_delivery._S16_SKILL_DELIVERY_V7 = True  # type: ignore[attr-defined]
    s15_s16_runtime_patch._direct_delivery = direct_delivery
