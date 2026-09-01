# Event Search Bridge Contract

本文件定义 `openclaw_bridge_http_search` 的本机桥接协议。它用于补充 S4/S9 的周边活动候选信号，不是生产事实源本身，也不能单独触发调价、审批或 live。

## 安全边界

- 仅允许本机 endpoint：`http://127.0.0.1:*` 或 `http://localhost:*`。
- 请求必须带 Bearer token；token 只放环境变量，不提交仓库。
- 返回必须包含可信 `service_id` 与 `source_type`。
- `source_type` 只接受 `verified_search` 或 `curated_event_feed`。
- `demo`、`placeholder`、`example.invalid` 结果不得作为商用活动展示。
- 搜索桥结果统一标记为 `partial_verified/search_inferred`，只能提升诊断置信度，不能作为直接调价触发。

## Request

```json
{
  "hotel_id": "xingfeng",
  "business_date": "2026-06-27",
  "query": "2026-06-27 xingfeng nearby hotel demand events"
}
```

## Response

```json
{
  "service_id": "hotel-ota-event-search-bridge",
  "source_type": "verified_search",
  "source_id": "local_bridge_or_provider_name",
  "fetched_at": "2026-06-27 12:00:00",
  "events": [
    {
      "event_id": "stable-id",
      "date": "2026-06-27",
      "event_name": "event name",
      "event_type": "concert | exam | sport | exhibition | holiday | other",
      "location": "location",
      "distance_km": 3.2,
      "source_url": "https://example.com/source",
      "confidence": 0.72,
      "expected_heat": "low | medium | high",
      "status": "candidate"
    }
  ]
}
```

## 本地联调

```bash
python tools/event_search_bridge_stub.py --port 8787
```

然后在私有 `market-source.json` 中配置：

```json
{
  "events": {
    "provider": "openclaw_bridge_http_search",
    "enabled": true,
    "endpoint": "http://127.0.0.1:8787/search",
    "expected_service_id": "hotel-ota-event-search-bridge",
    "source_type": "verified_search",
    "bearer_token_env": "HOTEL_OTA_EVENT_BRIDGE_CREDENTIAL"
  }
}
```

验证：

```bash
python runtime/hotel_ota_runtime.py event-bridge-check --hotel-id xingfeng --date 2026-06-27 --market-source-config /etc/hotel-ota-ai/market-source.json
```
