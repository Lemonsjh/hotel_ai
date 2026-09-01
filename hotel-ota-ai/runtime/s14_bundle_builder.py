from __future__ import annotations

import argparse
import contextlib
import io
import json
from datetime import date, datetime, timedelta
from typing import Any, Callable

from runtime.capability_results import (
    DEFAULT_CONTRACT_REVISION,
    DEFAULT_POLICY_REVISION,
    find_latest_capability_result,
    resolve_organization_id,
    save_s14_diagnosis_run,
)
from runtime import s14_operation_diagnosis as s14_diagnosis
from runtime.s14_operation_diagnosis import REQUIRED_CAPABILITY_IDS, diagnose_s14_request

CapabilityRunner = Callable[[str, dict[str, Any]], dict[str, Any]]

_COMMANDS = {
    "S2": "expected-occupancy",
    "S4": "market-context",
    "S7": "competition-alert",
    "S8": "promotion-plan",
    "S9": "conversion-diagnosis",
    "S10": "promotion-roi",
    "S12": "reputation-diagnosis",
    "S15": "baseline",
    "S16": "deviation",
    "S17": "customer-analysis",
}

_MODULE_NAMES = {
    "operating_revenue": "经营收益",
    "traffic_competition": "流量竞态",
    "conversion_orders": "转化订单",
    "price_inventory": "价格库存",
    "promotion_roi": "推广ROI",
    "content_entry": "内容入口",
    "reputation_service": "口碑服务",
    "execution_data_quality": "执行数据质量",
}

_AXIS_NAMES = {
    "sales_progress": "销售进度",
    "market_orders": "大盘订单",
    "market_share": "市场份额",
    "browse_users": "浏览",
    "first_conversion": "一转",
    "second_conversion": "二转",
    "price": "价格",
}

_SEVERITY_POINTS = {
    "critical": 100,
    "high": 75,
    "medium": 50,
    "low": 25,
    "info": 0,
}


def _parse_as_of(value: str | None) -> datetime:
    if value:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            return parsed
        return parsed.astimezone()
    return datetime.now().astimezone()


def _extract_json_from_stdout(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    if not stripped:
        return {
            "status": "data_gap",
            "reason": "capability_runner_no_output",
        }
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    for line in reversed(stripped.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {
        "status": "data_gap",
        "reason": "capability_runner_output_not_json",
        "output_preview": stripped[:300],
    }


def _command_argv(capability_id: str, context: dict[str, Any]) -> list[str]:
    hotel_id = str(context["hotel_id"])
    target_date = str(context["target_business_date"])[:10]
    as_of = _parse_as_of(str(context["as_of_datetime"]))
    as_of_hm = as_of.strftime("%H:%M")
    start_date = (date.fromisoformat(target_date) - timedelta(days=29)).isoformat()

    command = _COMMANDS[capability_id]
    args = ["--db", str(context["db_path"]), command, "--hotel-id", hotel_id]
    if capability_id == "S2":
        args.extend(["--date", target_date, "--as-of-time", as_of_hm])
    elif capability_id == "S4":
        args.extend(["--date", target_date])
    elif capability_id == "S15":
        args.extend(["--date", target_date])
    elif capability_id == "S16":
        args.extend(["--date", target_date, "--as-of-time", as_of_hm])
    elif capability_id == "S17":
        args.extend(
            [
                "--period-start",
                start_date,
                "--period-end",
                target_date,
                "--as-of-time",
                as_of_hm,
            ]
        )
    return args


def run_capability_via_cli(
    capability_id: str, context: dict[str, Any]
) -> dict[str, Any]:
    """Compatibility helper for explicitly invoked capability runs.

    Formal S14 no longer calls this helper automatically. It is retained only
    for callers that explicitly run an individual upstream capability outside
    the S14 diagnosis path.
    """
    if capability_id not in _COMMANDS:
        return {
            "status": "data_gap",
            "reason": "capability_command_not_registered",
            "missing_inputs": [capability_id],
        }
    try:
        from runtime import cli as runtime_cli

        output = io.StringIO()
        argv = _command_argv(capability_id, context)
        with contextlib.redirect_stdout(output):
            exit_code = runtime_cli.main(argv)
        result = _extract_json_from_stdout(output.getvalue())
        result.setdefault("runner_exit_code", exit_code)
        result.setdefault("runtime_command", _COMMANDS[capability_id])
        return result
    except SystemExit as exc:
        return {
            "status": "data_gap",
            "reason": "capability_command_argument_error",
            "runner_exit_code": int(exc.code or 1),
            "runtime_command": _COMMANDS.get(capability_id),
        }
    except Exception as exc:
        return {
            "status": "data_gap",
            "reason": f"capability_runner_failed:{exc.__class__.__name__}",
            "runtime_command": _COMMANDS.get(capability_id),
        }


def _drop_unrequested_capability_gaps(result: dict[str, Any]) -> dict[str, Any]:
    """Remove synthetic per-Skill missing alarms from formal S14 output.

    S14 judges the results that already exist. It does not require every Skill
    to run for every diagnosis request, so an absent upstream Skill is not by
    itself a business alarm. Coverage is determined by the modules that have
    valid deterministic inputs.
    """
    updated = dict(result)
    original_items = [item for item in result.get("items") or [] if isinstance(item, dict)]
    items = [
        item
        for item in original_items
        if not str(item.get("issue_code") or "").startswith("missing_input:")
    ]

    observed_modules = {
        str(module.get("module_id"))
        for module in result.get("modules") or []
        if isinstance(module, dict) and module.get("observed")
    }
    modules, coverage, risk, health = s14_diagnosis._module_projection(
        observed_modules=observed_modules,
        items=items,
    )

    existing_ids = {str(item.get("item_id")) for item in items}
    clusters: list[dict[str, Any]] = []
    for cluster in result.get("root_cause_clusters") or []:
        if not isinstance(cluster, dict):
            continue
        item_ids = [item_id for item_id in cluster.get("item_ids") or [] if str(item_id) in existing_ids]
        if not item_ids:
            continue
        clusters.append({**cluster, "item_ids": item_ids})

    severity_counts = {
        severity: sum(1 for item in items if item.get("severity") == severity)
        for severity in ("critical", "high", "medium", "low", "info")
    }
    data_limitations = []
    seen_limitations: set[str] = set()
    for item in items:
        if item.get("issue_type") not in {"data_gap", "conflict", "stale"} and not item.get("missing_inputs"):
            continue
        code = str(item.get("issue_code") or "").strip()
        if code and code not in seen_limitations:
            seen_limitations.add(code)
            data_limitations.append(code)

    if any(item.get("issue_type") == "conflict" for item in items):
        status = "conflict"
    elif not result.get("capability_result_count"):
        status = "data_gap"
    elif coverage < 1.0 or any(item.get("issue_type") in {"data_gap", "stale"} for item in items):
        status = "partial"
    else:
        status = "ok"

    updated.update(
        {
            "status": status,
            "items": items,
            "top_items": s14_diagnosis._top_root_cause_items(items),
            "root_cause_clusters": clusters,
            "modules": modules,
            "coverage_score": coverage,
            "observed_risk_score": risk,
            "observed_health_score": health,
            "severity_counts": severity_counts,
            "data_limitations": data_limitations,
            "business_result_generated": bool(observed_modules),
        }
    )
    return updated


def _fmt_number(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    if value in (None, "", "not_computable"):
        return "暂不可计算"
    return str(value)


def _axis_value_text(axis: dict[str, Any]) -> str:
    if axis.get("status") != "ok":
        return "暂无有效上游结果"
    parts = []
    for label, field in (("实际", "actual"), ("基准", "baseline"), ("差距", "delta"), ("成熟度", "maturity")):
        if axis.get(field) not in (None, ""):
            parts.append(f"{label}{_fmt_number(axis.get(field))}")
    return "；".join(parts) if parts else "已有结果，但无可展示数值"


def _build_metric_rows(result: dict[str, Any]) -> list[dict[str, str]]:
    modules = [item for item in result.get("modules") or [] if isinstance(item, dict)]
    items = [item for item in result.get("items") or [] if isinstance(item, dict)]
    axes = [item for item in result.get("decision_axes") or [] if isinstance(item, dict)]
    valid_modules = [module for module in modules if module.get("observed")]
    valid_inputs = int(result.get("capability_result_count") or 0)
    alignment_errors = sum(
        1 for item in items if str(item.get("issue_code") or "").startswith("capability_alignment:")
    )
    highest_issue_risk = max(
        (
            _SEVERITY_POINTS.get(str(item.get("severity")), 0)
            * max(0.0, min(1.0, float(item.get("confidence") or 0.0)))
            for item in items
            if not item.get("blocked_by")
        ),
        default=0.0,
    )
    module_risks = "；".join(
        f"{_MODULE_NAMES.get(str(module.get('module_id')), str(module.get('module_id')))}={_fmt_number(module.get('module_risk'))}"
        for module in valid_modules
    ) or "暂无有效模块"
    coverage = result.get("coverage_score")
    coverage_text = f"{float(coverage) * 100:.0f}%" if isinstance(coverage, (int, float)) else "0%"
    health_eligible = isinstance(coverage, (int, float)) and float(coverage) >= float(result.get("min_score_coverage") or 0.8)
    data_quality_count = sum(
        1
        for item in items
        if item.get("module_id") == "execution_data_quality"
        or item.get("issue_type") in {"data_gap", "conflict", "stale"}
    )
    blocked_count = sum(1 for item in items if item.get("blocked_by"))
    root_count = len(result.get("root_cause_clusters") or [])
    available_axes = sum(1 for axis in axes if axis.get("status") == "ok")
    top_labels = "；".join(_s14_issue_label(item) for item in (result.get("top_items") or [])[:5]) or "当前无已确认问题"
    ai_status = str(result.get("ai_analysis_status") or "not_requested")

    return [
        {
            "name": "输入资格判定",
            "formula": "输入有效 = 酒店范围一致 AND 目标日期一致 AND 数据时间≤查询截止时间 AND 结果版本兼容 AND 数据状态可用",
            "value": f"有效输入 {valid_inputs} 项；校验异常 {alignment_errors} 项",
            "description": "只校验已经存在的上游确定性结果；S14不会为了补齐输入自动运行其他Skill。",
        },
        {
            "name": "诊断模块归类",
            "formula": "上游结果按业务方向归入八个诊断模块之一",
            "value": f"有效模块 {len(valid_modules)}/8",
            "description": "经营收益、流量竞态、转化订单、价格库存、推广ROI、内容入口、口碑服务、执行数据质量。",
        },
        {
            "name": "严重度分值",
            "formula": "致命=100；高=75；中=50；低=25；提示=0",
            "value": "统一严重度计分规则已启用",
            "description": "用于问题风险分和模块风险分。",
        },
        {
            "name": "问题风险分",
            "formula": "问题风险分 = 严重度分值 × 问题置信度",
            "value": f"当前最高有效问题风险分 {_fmt_number(highest_issue_risk)}",
            "description": "被上游问题阻断的问题不参与模块风险计算。",
        },
        {
            "name": "模块风险分",
            "formula": "模块风险分 = MAX(本模块内未被上游问题阻断的问题风险分)",
            "value": module_risks,
            "description": "每个有效模块取最高风险，避免严重问题被平均稀释。",
        },
        {
            "name": "有效模块判定",
            "formula": "模块有效 = 至少存在一项有效确定性输入 AND 不存在导致整个模块失效的范围/时间/版本错误",
            "value": f"有效模块 {len(valid_modules)} 个",
            "description": "只有有效模块进入覆盖率和综合风险计算。",
        },
        {
            "name": "数据覆盖率",
            "formula": "数据覆盖率 = 有效模块权重之和 ÷ 100",
            "value": coverage_text,
            "description": "八模块权重固定为20/15/15/15/10/10/8/7。",
        },
        {
            "name": "综合风险分",
            "formula": "综合风险分 = Σ(有效模块权重 × 模块风险分) ÷ 有效模块权重之和",
            "value": _fmt_number(result.get("observed_risk_score")),
            "description": "缺失模块不按0风险参与计算。",
        },
        {
            "name": "健康分计算资格",
            "formula": "健康分可计算 = 数据覆盖率 ≥ 80%",
            "value": "可计算" if health_eligible else "不可计算",
            "description": "低于80%仍展示已有问题、数据缺口和核查建议。",
        },
        {
            "name": "综合健康分",
            "formula": "综合健康分 = 100 − 综合风险分",
            "value": _fmt_number(result.get("observed_health_score")),
            "description": "仅用于人工查看和经营排序，不触发任何经营动作。",
        },
        {
            "name": "数据问题优先",
            "formula": "数据缺失/冲突/过期/范围错误优先于依赖它们的经营结论",
            "value": f"当前数据质量类问题 {data_quality_count} 项",
            "description": "数据条件不成立时不强行输出经营异常。",
        },
        {
            "name": "阻断传播",
            "formula": "依赖数据不可用时，下游问题标记受上游影响且不参与模块风险计算",
            "value": f"当前受阻断问题 {blocked_count} 项",
            "description": "例如基线不可用时只标记进度暂不可判断。",
        },
        {
            "name": "根因聚合",
            "formula": "根因组 = 根因相同或证据来源相同的问题集合",
            "value": f"当前根因组 {root_count} 组",
            "description": "优先展示根问题，减少重复报警。",
        },
        {
            "name": "问题去重",
            "formula": "问题唯一标识 = 酒店 + 目标日期 + 模块 + 问题类型 + 作用范围 + 证据摘要",
            "value": f"当前唯一问题 {len(items)} 项",
            "description": "同一证据重复运行不重复生成相同问题。",
        },
        {
            "name": "问题排序",
            "formula": "严重程度 → 问题状态 → 所属模块 → 问题类型 → 问题编号",
            "value": top_labels,
            "description": "同等严重度优先数据冲突、数据缺口、数据过期、经营异常、观察项、正常项。",
        },
        {
            "name": "第一层经营透视",
            "formula": "主线结果 = 上游已计算的实际值、基准值、差距值和当前状态",
            "value": f"七条主线中 {available_axes} 条已有有效结果",
            "description": "固定展示销售进度、大盘订单、市场份额、浏览、一转、二转、价格；S14不重新计算。",
        },
        {
            "name": "第二层房型透视",
            "formula": "异常房型集合 = 达到异常条件或存在数据冲突的房型",
            "value": f"异常房型 {len(result.get('room_type_exceptions') or [])} 项",
            "description": "只展示异常房型，不把酒店整体异常平均分摊到房型。",
        },
        {
            "name": "第三层商品透视",
            "formula": "商品候选集合 = S5或S6已经生成并通过规则校验的商品级候选",
            "value": f"已有商品候选/事实 {len(result.get('product_layer') or [])} 项",
            "description": "S14不能自行产生新的涨价或降价方案。",
        },
        {
            "name": "结果交接",
            "formula": "价格问题→S5/S6；推广问题→S8；评论问题→S13",
            "value": f"当前已有受控交接 {len(result.get('handoffs') or [])} 项",
            "description": "S14只传递已有问题和结果，不负责审批或执行。",
        },
        {
            "name": "直接执行资格",
            "formula": "是否允许直接执行 = 否",
            "value": "否",
            "description": "健康分、风险分和问题排序均不能直接触发经营动作。",
        },
        {
            "name": "AI解释资格",
            "formula": "AI可用 = 确定性诊断、风险评分和排序全部完成后",
            "value": f"当前AI状态：{ai_status}",
            "description": "AI只能解释已有诊断，不能新增问题、调整严重度、修改评分或生成经营动作。",
        },
    ]


def build_and_run_s14(
    *,
    organization_id: str | None,
    hotel_id: str,
    target_business_date: str,
    as_of_datetime: str,
    db_path: str,
    contract_revision: str = DEFAULT_CONTRACT_REVISION,
    policy_revision: str = DEFAULT_POLICY_REVISION,
    refresh: bool = False,
    capability_runner: CapabilityRunner | None = None,
    handoffs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose S14 from already-existing versioned deterministic results only.

    Formal S14 does not auto-run S2/S4/S7/S8/S9/S10/S12/S15/S16/S17. It reads
    whatever aligned versioned results already exist for the exact hotel/date/
    as-of context, then performs only S14's own qualification, classification,
    risk, coverage, health, ordering and projection logic.
    """
    del refresh, capability_runner
    requested_org = str(organization_id or "").strip()
    stored_org = resolve_organization_id(db_path, hotel_id)
    if requested_org:
        resolved_org = requested_org
        organization_resolution_source = "request"
    elif stored_org:
        resolved_org = stored_org
        organization_resolution_source = "hotels.org_id"
    else:
        resolved_org = f"hotel-scope:{hotel_id}"
        organization_resolution_source = "derived_exact_hotel_scope"

    capability_results: list[dict[str, Any]] = []
    collection: list[dict[str, Any]] = []
    for capability_id in REQUIRED_CAPABILITY_IDS:
        saved = find_latest_capability_result(
            db_path=db_path,
            organization_id=resolved_org,
            hotel_id=hotel_id,
            capability_id=capability_id,
            target_business_date=target_business_date,
            as_of_datetime=as_of_datetime,
            contract_revision=contract_revision,
            policy_revision=policy_revision,
        )
        if saved is None:
            collection.append(
                {
                    "capability_id": capability_id,
                    "source": "not_present",
                    "status": "not_present",
                }
            )
            continue
        capability_results.append(saved)
        collection.append(
            {
                "capability_id": capability_id,
                "source": "saved_versioned_result",
                "status": saved["status"],
                "result_id": saved["result_id"],
                "result_version": saved["result_version"],
            }
        )

    request = {
        "organization_id": resolved_org,
        "hotel_id": str(hotel_id),
        "target_business_date": str(target_business_date)[:10],
        "as_of_datetime": str(as_of_datetime),
        "contract_revision": contract_revision,
        "policy_revision": policy_revision,
        "capability_results": capability_results,
        "handoffs": list(handoffs or []),
    }
    result = _drop_unrequested_capability_gaps(diagnose_s14_request(request))
    result["capability_collection"] = collection
    result["capability_collection_summary"] = {
        "saved_count": sum(1 for item in collection if item["source"] == "saved_versioned_result"),
        "missing_count": sum(1 for item in collection if item["source"] == "not_present"),
        "generated_count": 0,
        "ok_count": sum(1 for item in collection if item["status"] == "ok"),
        "degraded_count": sum(
            1
            for item in collection
            if item["source"] == "saved_versioned_result" and item["status"] != "ok"
        ),
    }
    result["auto_run_upstream_capabilities"] = False
    result["organization_resolution_source"] = organization_resolution_source
    result["metric_rows"] = _build_metric_rows(result)
    if organization_resolution_source == "derived_exact_hotel_scope":
        limitations = list(result.get("data_limitations") or [])
        if "organization_id_derived_from_exact_hotel_scope" not in limitations:
            limitations.append("organization_id_derived_from_exact_hotel_scope")
        result["data_limitations"] = limitations
        if result.get("status") == "ok":
            result["status"] = "partial"

    run_id = save_s14_diagnosis_run(
        result,
        db_path=db_path,
        organization_id=resolved_org,
        hotel_id=hotel_id,
        target_business_date=target_business_date,
        as_of_datetime=as_of_datetime,
        contract_revision=contract_revision,
        policy_revision=policy_revision,
    )
    result["diagnosis_run_id"] = run_id
    result["result_persisted"] = True
    return result


def build_s14_cli_parser(default_db: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="s14-diagnosis",
        description="Compose S14 from already-existing versioned deterministic results; never auto-run upstream Skills.",
    )
    parser.add_argument("--db", default=default_db)
    parser.add_argument("--organization-id")
    parser.add_argument("--hotel-id", required=True)
    parser.add_argument("--date")
    parser.add_argument("--as-of-datetime")
    parser.add_argument("--contract-revision", default=DEFAULT_CONTRACT_REVISION)
    parser.add_argument("--policy-revision", default=DEFAULT_POLICY_REVISION)
    parser.add_argument("--refresh", action="store_true", help="Deprecated compatibility flag; S14 does not auto-run upstream Skills.")
    return parser


def run_s14_cli(argv: list[str], *, default_db: str) -> dict[str, Any]:
    parser = build_s14_cli_parser(default_db)
    args = parser.parse_args(argv)
    as_of = _parse_as_of(args.as_of_datetime)
    target_date = args.date or as_of.date().isoformat()
    return build_and_run_s14(
        organization_id=args.organization_id,
        hotel_id=args.hotel_id,
        target_business_date=target_date,
        as_of_datetime=as_of.isoformat(timespec="seconds"),
        db_path=args.db,
        contract_revision=args.contract_revision,
        policy_revision=args.policy_revision,
        refresh=args.refresh,
    )


def render_s14_feishu_text(result: dict[str, Any]) -> str:
    status_labels = {
        "ok": "正常",
        "partial": "部分可用",
        "conflict": "存在冲突",
        "data_gap": "数据不足",
    }
    coverage = result.get("coverage_score")
    coverage_text = f"{float(coverage) * 100:.0f}%" if isinstance(coverage, (int, float)) else "0%"
    risk_text = _fmt_number(result.get("observed_risk_score"))
    health_text = _fmt_number(result.get("observed_health_score"))
    lines = [
        "【S14 综合运营诊断】",
        f"目标营业日：{result.get('target_business_date') or '-'}",
        f"数据截止：{result.get('as_of_datetime') or '-'}",
        f"状态：{status_labels.get(str(result.get('status')), result.get('status') or '-')}",
        f"数据覆盖率：{coverage_text}",
        f"综合风险分：{risk_text}",
        f"综合健康分：{health_text}",
        "口径：S14只消费已经存在的上游确定性结果，不自动运行或补跑其他Skill。",
    ]

    axes = [item for item in result.get("decision_axes") or [] if isinstance(item, dict)]
    if axes:
        lines.append("")
        lines.append("【第一层经营透视】")
        for axis in axes:
            axis_name = _AXIS_NAMES.get(str(axis.get("axis_id")), str(axis.get("axis_id") or "主线"))
            lines.append(f"- {axis_name}：{_axis_value_text(axis)}")

    room_items = result.get("room_type_exceptions") or []
    lines.append("")
    lines.append(f"【第二层房型透视】异常房型 {len(room_items)} 项")
    for item in room_items[:5]:
        if not isinstance(item, dict):
            continue
        room_name = item.get("room_type_name") or item.get("room_type_id") or "未命名房型"
        issue = item.get("issue_code") or item.get("issue_type") or "异常"
        lines.append(f"- {room_name}：{issue}")

    products = result.get("product_layer") or []
    lines.append("")
    lines.append(f"【第三层商品透视】已有商品候选/事实 {len(products)} 项")
    for item in products[:5]:
        if not isinstance(item, dict):
            continue
        label = item.get("product_name") or item.get("ota_product_id") or item.get("product_id") or "商品"
        state = item.get("status") or item.get("action") or item.get("candidate_type") or "已有确定性结果"
        lines.append(f"- {label}：{state}")

    top_items = result.get("top_items") or []
    if top_items:
        lines.append("")
        lines.append("【优先问题】")
        for index, item in enumerate(top_items[:5], start=1):
            if not isinstance(item, dict):
                continue
            blocked = "（受上游阻断）" if item.get("blocked_by") else ""
            lines.append(f"{index}. [{item.get('severity')}] {_s14_issue_label(item)}{blocked}")

    lines.append("")
    lines.append("【S14规范指标】")
    for index, row in enumerate(result.get("metric_rows") or [], start=1):
        if not isinstance(row, dict):
            continue
        lines.append(f"{index}. {row.get('name')}：{row.get('value')}")
        lines.append(f"   公式：{row.get('formula')}")
        lines.append(f"   说明：{row.get('description')}")

    lines.append("")
    lines.append("边界：S14不直接调价、投放、审批、创建执行任务或发布评论；AI仅可解释已完成的确定性诊断。")
    return "\n".join(lines)


def _s14_issue_label(item: dict[str, Any]) -> str:
    code = str(item.get("issue_code") or "数据质量待核对")
    if code.startswith("capability_status:S9:data_gap"):
        return "S9 流量/转化数据缺失"
    if code.startswith("capability_status:S15:data_gap"):
        return "S15 销售基准线数据不足"
    if code.startswith("capability_status:S16:data_gap"):
        return "S16 当日销售进度暂不可判断"
    if code.startswith("axis_source_conflict:sales_progress"):
        return "销售进度基线来源不一致"
    if code.startswith("capability_status:S2:partial"):
        return "S2 经营快照部分数据缺失"
    if code.startswith("capability_status:S4:partial"):
        return "S4 市场行情部分数据缺失"
    return code.replace("_", " ")


def is_s14_operation_message(message: str) -> bool:
    text = str(message or "")
    lowered = text.lower()
    if any(term in text for term in ("演示", "demo", "Demo")):
        return False
    if "S14-EXT" in text or "s14-ext" in lowered:
        return False
    return (
        "OTA运营诊断" in text
        or "OTA 运营诊断" in text
        or "综合运营诊断" in text
        or "本店运营诊断" in text
        or "本店OTA运营诊断" in text
        or "本店 OTA运营诊断" in text
        or "运行S14" in text
        or "运行 S14" in text
        or "跑一下S14" in text
        or "跑一下 S14" in text
        or "查看S14" in text
        or "查看 S14" in text
        or "s14 diagnosis" in lowered
    )


__all__ = [
    "build_and_run_s14",
    "build_s14_cli_parser",
    "is_s14_operation_message",
    "render_s14_feishu_text",
    "run_capability_via_cli",
    "run_s14_cli",
]
