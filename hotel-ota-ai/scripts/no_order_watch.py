#!/usr/bin/env python3
"""无进单监控：每 30 分钟检查一次美团支付订单数是否增长。

规则：
- 读取 meituan_ota_business_metrics.PAY_ORDER_CNT（日累计支付订单数）与快照时间。
- 若数据快照有更新但订单数未增长，累计"无新订单"时长；
- 连续 >= 90 分钟无新订单且未提醒过 -> 输出提醒文本（供 cron announce 发送）；
- 订单数恢复增长后重置提醒状态。

输出 JSON：{"need_alert": bool, "message": str, "detail": {...}}
仅供定时任务使用；只读，不写库。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

HOTEL_ID = os.environ.get("HOTEL_OTA_WATCH_HOTEL_ID", "puyue")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(BASE_DIR, "runtime", "hotel_ota_runtime.py")
STATE_DIR = os.environ.get("HOTEL_OTA_WATCH_STATE_DIR", os.path.join(BASE_DIR, "state"))
STATE_FILE = os.path.join(STATE_DIR, "no_order_watch.json")
NO_NEW_ORDER_MINUTES = int(os.environ.get("HOTEL_OTA_WATCH_MINUTES", "90"))
CHECK_INTERVAL_MINUTES = 30  # 与 cron 节奏一致

HOURS_ACTIVE = (8, 23)  # 营业时段 08:00-23:59 才监控，避免夜间正常无单误报


def now_local() -> datetime:
    return datetime.now()


def active_hours() -> bool:
    return HOURS_ACTIVE[0] <= now_local().hour < HOURS_ACTIVE[1] + 1


def query_pay_orders() -> dict:
    """调用 runtime database-query 读取美团 PAY_ORDER_CNT。"""
    cmd = [
        sys.executable, RUNTIME, "database-query",
        "--db-kind", "mysql",
        "--template", "ota_business_metrics",
        "--hotel-id", HOTEL_ID,
        "--date", now_local().strftime("%Y-%m-%d"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        return {"status": "error", "error": proc.stderr[-500:] or proc.stdout[-500:]}
    try:
        payload = json.loads(proc.stdout)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"parse_error: {exc}"}
    rows = (payload.get("payload") or {}).get("rows") or []
    snapshot = (payload.get("payload") or {}).get("data_snapshot_time")
    pay = None
    for row in rows:
        if row.get("metric_code") == "PAY_ORDER_CNT":
            try:
                pay = float(row.get("metric_value"))
            except (TypeError, ValueError):
                pay = None
            break
    return {
        "status": "ok",
        "pay_orders": pay,
        "snapshot_time": snapshot or (payload.get("payload") or {}).get("data_snapshot_time"),
        "data_age_hours": (payload.get("payload") or {}).get("data_age_hours"),
        "freshness": (payload.get("payload") or {}).get("freshness_status"),
    }


def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def main() -> int:
    if not active_hours():
        save_state(load_state())  # 保持原状态
        print(json.dumps({"need_alert": False, "message": "", "detail": {"reason": "outside_active_hours"}}, ensure_ascii=False))
        return 0

    result = query_pay_orders()
    now = now_local()
    if result.get("status") != "ok":
        print(json.dumps({"need_alert": False, "message": "", "detail": {"reason": "query_error", "error": result.get("error")}}, ensure_ascii=False))
        return 0

    pay = result.get("pay_orders")
    snap = result.get("snapshot_time")
    state = load_state()
    prev_pay = state.get("pay_orders")
    prev_snap = state.get("snapshot_time")
    no_new_since = state.get("no_new_since")  # ISO str or None
    alerted_at = state.get("alerted_at")

    if pay is None:
        print(json.dumps({"need_alert": False, "message": "", "detail": {"reason": "pay_order_metric_missing"}}, ensure_ascii=False))
        return 0

    # 数据未刷新（快照时间没变）时不算"无新订单"，避免把采集停摆误判为没进单
    snapshot_refreshed = (prev_snap is None) or (snap != prev_snap)

    if prev_pay is not None and snapshot_refreshed and pay <= prev_pay:
        if no_new_since is None:
            no_new_since = now.isoformat()
        # 无新订单持续时长（从第一次发现无增长开始）
        try:
            start = datetime.fromisoformat(no_new_since)
            silent_minutes = (now - start).total_seconds() / 60.0
        except Exception:  # noqa: BLE001
            start = now
            silent_minutes = 0.0
    else:
        no_new_since = None
        alerted_at = None
        silent_minutes = 0.0

    state.update(
        {
            "pay_orders": pay,
            "snapshot_time": snap,
            "no_new_since": no_new_since,
            "alerted_at": alerted_at,
            "last_check": now.isoformat(),
        }
    )
    save_state(state)

    detail = {
        "pay_orders": pay,
        "prev_pay_orders": prev_pay,
        "snapshot_time": snap,
        "snapshot_refreshed": snapshot_refreshed,
        "silent_minutes": round(silent_minutes, 1) if no_new_since else 0.0,
        "data_age_hours": result.get("data_age_hours"),
    }

    if no_new_since and silent_minutes >= NO_NEW_ORDER_MINUTES and not alerted_at:
        state["alerted_at"] = now.isoformat()
        save_state(state)
        message = (
            f"⚠️ 无进单提醒｜{now.strftime('%Y-%m-%d %H:%M')}\n"
            f"美团支付订单数已连续约 {int(silent_minutes)} 分钟未增长（当前累计 {pay:.0f} 单）。\n"
            f"数据截至 {snap or '未知'}（采集可能滞后约 {result.get('data_age_hours') or '?'} 小时），请留意是真实无单还是数据延迟。\n"
            f"可发送「进度诊断」查看当前销售情况。"
        )
        print(json.dumps({"need_alert": True, "message": message, "detail": detail}, ensure_ascii=False))
        return 0

    print(json.dumps({"need_alert": False, "message": "", "detail": detail}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
