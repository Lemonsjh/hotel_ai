from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

VERSION = "s15-s16-complete-output.v1"
_INSTALLED = False


def n(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def num(value: Any, digits: int = 1) -> str:
    value = n(value)
    if value is None:
        return "—"
    return str(int(round(value))) if abs(value-round(value)) < 1e-9 else f"{value:.{digits}f}"


def money(value: Any) -> str:
    value = n(value)
    return "—" if value is None else f"¥{value:,.0f}"


def pct(value: Any) -> str:
    value = n(value)
    return "—" if value is None else f"{value*100:.1f}%"


def pp(value: Any) -> str:
    value = n(value)
    return "—" if value is None else f"{value:+.1f}pp"


def label(value: Any) -> str:
    labels = {
        "severe_slow":"严重偏慢","significant_slow":"明显偏慢","slow":"偏慢","normal":"正常",
        "fast":"偏快","significant_fast":"明显偏快","cold":"偏冷","hot":"偏热",
        "weak":"偏弱","significant_weak":"明显偏弱","soft":"略弱","strong":"偏强",
        "high":"偏高","low":"偏低","sample_insufficient":"样本不足","unavailable":"暂不可判断",
    }
    return labels.get(str(value), str(value or "暂不可判断"))


def hour_of(payload: Mapping[str, Any]) -> int:
    text = str(payload.get("as_of_datetime") or "")
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).hour
    except ValueError:
        return 23


def point(points: Sequence[Mapping[str, Any]], hour: int) -> Mapping[str, Any]:
    exact = next((row for row in points if int(row.get("hour", -1)) == hour), None)
    if exact:
        return exact
    earlier = [row for row in points if isinstance(row.get("hour"), int) and row["hour"] <= hour]
    return max(earlier, key=lambda row: row["hour"]) if earlier else {}


def confidence(axis: Mapping[str, Any]) -> str:
    return f"样本{int(axis.get('sample_count') or 0)}天" + (f"，{axis.get('baseline_confidence_level') or axis.get('baseline_tier')}" if axis.get("baseline_confidence_level") or axis.get("baseline_tier") else "")


def s15_message(payload: Mapping[str, Any]) -> str:
    if payload.get("status") != "ok":
        gaps = payload.get("data_gaps") or [payload.get("reason") or "基准事实不可用"]
        return "S15 完整经营基准线暂不可用：" + "；".join(map(str, gaps)) + "。"
    a = payload.get("operating_analysis") or {}
    sales, market, share = a.get("sales") or {}, a.get("market") or {}, a.get("market_share") or {}
    browse, first, second = a.get("browse") or {}, a.get("first_conversion") or {}, a.get("second_conversion") or {}
    price, lead = a.get("price") or {}, a.get("lead_price") or {}
    hotel, rooms, hour = payload.get("hotel") or {}, payload.get("room_types") or {}, hour_of(payload)
    hp = point(hotel.get("hourly_points") or [], hour)
    target = n(hotel.get("effective_target_room_nights")); completion = n((hp.get("target_completion") or {}).get("median"))
    expected = target*completion if target is not None and completion is not None else None
    age = int(sales.get("checkpoint_gap_minutes")) if sales.get("checkpoint_gap_minutes") is not None else None
    stale = age is not None and age > 120
    dmap = {"sales_progress_unavailable":"销售事实不足","sales_on_track_or_ahead":"销售进度正常或偏快","sales_progress_slow":"销售进度偏慢","market_cold_share_not_weak":"市场偏冷且份额未弱","market_share_declining":"估算份额下降","traffic_insufficient":"浏览不足","entry_attractiveness_weak":"一转偏弱","detail_page_conversion_weak":"二转偏弱","specific_room_prices_high":"部分房型商品价偏高","no_single_root_cause_confirmed":"未锁定单一根因","stale_current_sales_fact":"销售快照偏旧，仅作趋势判断"}
    diagnoses = [dmap.get(str(v), str(v)) for v in a.get("diagnosis") or []]
    lines = [
        f"S15 完整经营基准线｜{payload.get('target_date') or payload.get('business_date') or '-'}｜截至 {str(payload.get('as_of_datetime') or '-')[-8:-3]}",
        "判断顺序：销售进度 → 美团大盘订单 → 美团本店份额 → 美团浏览 → 美团一转 → 美团二转 → 房型价格 → 美团引流价及排名 → 动作。",
        "综合结论：" + ("；".join(diagnoses) if diagnoses else "当前仅展示基准事实") + "。",
        "", "一、销售进度基准线（全店）",
        f"- 历史同类日参考终值 {num(target)}间；当前时点参考应售 {num(expected)}间。",
        f"- 当前承诺已售 {num(sales.get('committed_sold'))}/{num(sales.get('total_rooms'))}间；完成线偏差 {pp(sales.get('sales_progress_delta_pp'))}，判定{label(sales.get('status'))}。",
        f"- 容量历史线偏差 {pp(sales.get('capacity_progress_delta_pp'))}；剩余可售 {num(sales.get('available_rooms'))}间，占比 {pct(sales.get('remaining_inventory_ratio'))}。",
    ]
    if age is not None:
        lines.append(f"- 最新完整批次距请求约{age}分钟；{'仅作趋势，不触发动作' if stale else '时效可用于当前判断'}。")
    lines += ["", "二、销售进度基准线（全部房型）"]
    facts = {str(row.get("room_type_id")):row for row in sales.get("room_type_results") or [] if row.get("room_type_id")}
    for room_id, room in sorted(rooms.items(), key=lambda x:str(x[0])):
        fact = facts.get(str(room_id), {}); rp = point(room.get("hourly_points") or [], hour)
        rt = n(room.get("effective_target_room_nights")); rc = n((rp.get("target_completion") or {}).get("median")); re = rt*rc if rt is not None and rc is not None else None
        tl, cl = fact.get("target_line") or {}, fact.get("capacity_line") or {}
        name = room.get("room_type_name") or fact.get("room_type_name") or room_id
        lines.append(f"- {name}：参考终值{num(rt)}间，当前应售{num(re)}间，实际{num(fact.get('committed_sold'))}/{num(fact.get('total_rooms'))}间；完成线{label(tl.get('status'))}({pp(tl.get('delta_pp'))})，容量线{label(cl.get('status'))}({pp(cl.get('delta_pp'))})。")
    lines += [
        "", "三、美团大盘订单基准线（估算）",
        f"- 美团当前估算{num(market.get('estimated_market_orders'))}单，历史同类日中位{num(market.get('baseline_estimated_market_orders'))}单，热度比{num(market.get('market_heat_ratio'),2)}，判定{label(market.get('status'))}。",
        f"- 美团竞争圈估算：同行平均{num(market.get('peer_average_orders'))}单/店 × 竞争圈{num(market.get('peer_hotel_count'))}家，并四舍五入为整数；{confidence(market)}。",
        "", "四、美团本店市场份额基准线（估算）",
        f"- 美团当前{pct(share.get('current_estimated_market_share'))}，历史同类日{pct(share.get('baseline_estimated_market_share'))}，变化{pp(share.get('delta_pp'))}，判定{label(share.get('status'))}。",
        "- 分母来自美团估算竞争圈订单，不冒充平台直接提供的市场总订单。",
        "", "五、美团浏览基准线（日级）",
        f"- 当前{num(browse.get('current'))}，历史同类日中位{num(browse.get('baseline_median'))}，比值{num(browse.get('ratio'),2)}，判定{label(browse.get('status'))}；{confidence(browse)}。",
        "- 美团经营指标每日一份，不生成小时浏览基准。",
        "", "六、美团一转基准线（日级：曝光→浏览）",
        f"- 当前{pct(first.get('current'))}，历史同类日中位{pct(first.get('baseline_median'))}，比值{num(first.get('ratio'),2)}，判定{label(first.get('status'))}。",
        f"- 样本门槛：曝光{num(first.get('exposure_users'))}、浏览{num(first.get('browse_users'))}；{confidence(first)}。",
        "", "七、美团二转基准线（日级：浏览→支付）",
        f"- 当前{pct(second.get('current'))}，自身中位{pct(second.get('baseline_median'))}，P25 {pct(second.get('baseline_p25'))}，支付订单{num(second.get('pay_orders'))}。",
        f"- 美团近30日同行指数{num(second.get('conversion_index_vs_market'),2)}；判定{'偏弱' if second.get('is_weak') else label(second.get('status'))}。美团30日滚动汇总不拆成30个历史样本。",
        "", "八、房型历史价格基准线与当前美团商品价",
    ]
    current = {str(row.get("room_type_id")):row for row in price.get("room_results") or [] if row.get("room_type_id")}
    for room_id, room in sorted(rooms.items(), key=lambda x:str(x[0])):
        baseline, now = room.get("price_baseline") or {}, current.get(str(room_id), {})
        name = room.get("room_type_name") or now.get("room_type_name") or room_id
        product = now.get("ota_product_name") or now.get("ota_product_id")
        lines.append(f"- {name}：P20/中位/P80={money(baseline.get('p20'))}/{money(baseline.get('median'))}/{money(baseline.get('p80'))}；当前{money(now.get('current_price')) if now else '可比商品价不可用'}" + (f"，商品{product}" if product else "") + f"；{label(now.get('price_status')) if now else '仅有历史基准'}。")
    lines += [
        "- 普通全天房、超级团购、钟点房分开解释；价格偏高本身不直接触发降价。",
        "", "九、美团引流价及排名基准线（日级）",
        f"- 美团当前引流价{money(lead.get('current'))}，历史中位{money(lead.get('baseline_median'))}，比值{num(lead.get('ratio'),2)}；美团同行均价{money(lead.get('peer_average'))}，美团竞争圈排名{num(lead.get('rank'))}/{num(lead.get('rank_total'))}。",
        "- 只能形成美团酒店级引流价与排名基准，不能反推历史引流房型身份。",
        "", "十、动作判断",
    ]
    amap = {"no_action":"暂不动作","suggest_enable_ad_slot":"由S8核验后开启/恢复广告位","suggest_disable_ad_slot":"由S8核验后关闭广告位","conservative_inventory_management":"市场偏冷，保守管理库存","investigate_traffic_before_spend":"先排查流量与转化","optimize_entry_display":"优化列表入口与引流承接","suggest_room_price_reduction":"由S5做具体房型调价预览与护栏校验","investigate_detail_conversion":"排查详情页成交承接","continue_observation":"继续观察","suppress_actions_due_to_stale_fact":"销售事实偏旧，禁止动作候选"}
    for action in a.get("actions") or []:
        text = amap.get(str(action.get("action_type")), str(action.get("action_type")))
        if action.get("target_room_type_ids"):
            text += "；房型" + "、".join(map(str, action.get("target_room_type_ids")))
        lines.append("- " + text + "；仅建议，不直接执行。")
    if not a.get("actions"):
        lines.append("- 当前无合格动作候选。")
    gaps = list(payload.get("data_gaps") or []); unavailable = list((payload.get("unavailable_baseline_families") or {}).keys())
    lines += [
        "", "十一、基准健康与数据边界",
        f"- 销售小时历史选中{len(payload.get('selected_dates') or [])}个同类日期；缺小时不插值、不补零。",
        f"- 查询/质量提示：{'；'.join(map(str,gaps)) if gaps else '无阻断性查询错误'}。",
        f"- 当前不可用基准：{'、'.join(unavailable) if unavailable else '无额外不可用项'}。",
        "- 渠道口径：上述大盘、份额、浏览、一转、二转、引流价与排名均为美团；携程指标如单独展示必须显式标注“携程”，不得与美团竞争圈混写。",
        "- 携程酒店主体或canonical房型不一致时整组禁用，不作为本酒店经营、价格或同行基准。",
    ]
    return "\n".join(lines)


def s16_message(report: Mapping[str, Any]) -> str:
    if report.get("status") not in {"ok","partial"}:
        return f"S16销售进度暂不可判断：{report.get('reason') or '当前事实或S15基准不可用'}。采集暂停造成的旧完整批次应降级使用，只有无合法批次才属于数据缺口。"
    hotel = report.get("hotel_result") or {}; cap = hotel.get("capacity_line") or {}; target = hotel.get("target_line") or {}
    age = int(report.get("checkpoint_gap_minutes")) if report.get("checkpoint_gap_minutes") is not None else None
    lines = [
        f"S16 销售进度与房型结构｜{report.get('target_date') or '-'}｜截至{str(report.get('as_of_datetime') or '-')[-8:-3]}",
        f"全店承诺已售{num(hotel.get('committed_sold'))}/{num(hotel.get('total_rooms'))}间；参考终值{num(hotel.get('effective_target_room_nights'))}间。",
        f"目标完成线{label(target.get('status'))}，偏差{pp(target.get('delta_pp'))}，检查点差{num(target.get('room_gap'))}间，距终值{num(target.get('remaining_target_gap'))}间。",
        f"容量历史线{label(cap.get('status'))}，偏差{pp(cap.get('delta_pp'))}。",
    ]
    if age is not None:
        lines.append(f"事实批次距请求约{age}分钟；{'只作趋势和结构判断，禁止动作' if age>120 else '可用于当前判断'}。")
    lines += ["", "全部房型："]
    for room in report.get("room_type_results") or []:
        tl, cl = room.get("target_line") or {}, room.get("capacity_line") or {}; name = room.get("room_type_name") or room.get("room_type_id") or "未知房型"
        lines.append(f"- {name}：已售{num(room.get('committed_sold'))}/{num(room.get('total_rooms'))}间，参考终值{num(room.get('effective_target_room_nights'))}间；完成线{label(tl.get('status'))}({pp(tl.get('delta_pp'))}，检查点差{num(tl.get('room_gap'))}间，终值差{num(tl.get('remaining_target_gap'))}间)；容量线{label(cl.get('status'))}({pp(cl.get('delta_pp'))})。")
    structure = report.get("structure_summary") or {}; smap = {"broad_based_slowdown":"多数房型普遍偏慢","room_type_structural_lag":"重要房型结构性偏慢","mix_offset_detected":"快慢房型互相抵消"}
    labels = [smap.get(str(v),str(v)) for v in structure.get("labels") or structure.get("structure_labels") or []]
    lines += ["", "房型结构：", f"- 偏慢{structure.get('slow_room_type_count',0)}个，偏快{structure.get('fast_room_type_count',0)}个。", f"- 结构结论：{'；'.join(labels) if labels else '未发现额外结构标签'}。", "结论边界：S16只判断全店进度和房型结构，不分析大盘、份额、浏览、一转、二转、价格，不生成动作。"]
    return "\n".join(lines)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from runtime.sales_progress import presentation
    from runtime.decisions import baseline as baseline_decision, deviation as deviation_decision
    from runtime import s15_s16_runtime_patch

    def attach15(payload: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(payload); text = s15_message(result)
        result.update({"summary":text,"user_message":text,"business_view_version":"s15.zh-CN.complete-matrix.v1","ai_analysis_allowed":False,"ai_rewrite_allowed":False,"delivery_mode":"authoritative_runtime_text","must_send_text_verbatim":True})
        return result

    def attach16(payload: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(payload); text = s16_message(result)
        result.update({"summary":text,"user_message":text,"business_view_version":"s16.zh-CN.complete-progress.v1","ai_analysis_allowed":False,"ai_rewrite_allowed":False,"delivery_mode":"authoritative_runtime_text","must_send_text_verbatim":True})
        return result

    presentation.build_s15_user_message = s15_message; presentation.build_s16_user_message = s16_message
    presentation.attach_s15_user_view = attach15; presentation.attach_s16_user_view = attach16
    baseline_decision.attach_s15_user_view = attach15; deviation_decision.attach_s16_user_view = attach16

    def direct(result: dict[str, Any], role: str | None = None) -> tuple[dict[str, Any],dict[str,Any]]:
        from runtime.safety.feishu_output import feishu_output_gate
        text = str(result.get("user_message") or result.get("summary") or "当前结果暂不可用。")
        gate = feishu_output_gate(source="feishu",content_kind="text",message=text)
        profile = result.get("output_profile") or ("owner_business" if role in {"admin","owner"} else "operator_workbench")
        warnings=[]
        if gate.get("status") != "ok":
            text="您好，当前业务摘要不能通过飞书业务通道发送。"; warnings.append(f"feishu_output_gate:{gate.get('blocked_reason')}")
        contract={"mode":"verbatim_runtime_text","must_send_text_verbatim":True,"ai_rewrite_allowed":False,"ai_analysis_allowed":False,"additional_tool_calls_allowed":False,"contract_version":VERSION}
        rendered={"status":"ok" if gate.get("status")=="ok" else "blocked","output_profile":profile,"text":text,"visible_fields":["user_message"],"hidden_fields":["internal_algorithm_fields"],"message_send_attempted":False,"template":"s15_complete_matrix" if result.get("intent")=="sales_baseline_demo" else "s16_complete_progress","delivery_mode":"authoritative_runtime_text","must_send_text_verbatim":True,"ai_rewrite_allowed":False}
        send={"text":text,"card":None,"send_allowed":gate.get("status")=="ok","output_profile":profile,"warnings":warnings,"data_source_type":result.get("data_source_type"),"freshness_status":result.get("freshness_status"),"delivery_mode":"authoritative_runtime_text","must_send_text_verbatim":True,"ai_rewrite_allowed":False,"ai_analysis_allowed":False,"assistant_response_contract":contract}
        return rendered,send
    s15_s16_runtime_patch._direct_delivery = direct
