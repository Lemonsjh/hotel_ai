# S14-EXT HTML Report Contract

S14-EXT does not use Feishu links as per-event source links. The primary Feishu link must point to a generated HTML analysis report.

## Target flow

```text
S14-EXT diagnosis
  -> build structured third-party context result
  -> render an HTML report
  -> write it under public/s14-reports/
  -> generate a public report_url
  -> send a Feishu interactive card with a button
  -> user clicks the button and opens the actual HTML report
```

## Required runtime output

```json
{
  "status": "ok",
  "report_type": "s14_ext_third_party",
  "run_id": "s14ext-xingfeng-20260629153022-a91c3e",
  "hotel_id": "xingfeng",
  "hotel_name": "星锋电竞酒店",
  "period_start": "2026-06-29",
  "period_end": "2026-06-29",
  "third_party_score": 72,
  "risk_level": "medium",
  "opportunity_level": "medium",
  "summary": "周边活动和天气对今晚需求有中等拉动。",
  "report_file_path": "<internal path, never send to Feishu>",
  "report_url": "https://example.com/s14-reports/s14_ext_report_xingfeng_20260629153022_a91c3e.html",
  "feishu_card": {}
}
```

## Environment variables

```text
S14_REPORT_OUTPUT_DIR=/opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports
S14_PUBLIC_BASE_URL=https://your-domain.example/s14-reports
S14_REPORT_RETENTION_DAYS=30
```

If `S14_PUBLIC_BASE_URL` is missing in production Feishu, return `data_gap` with reason `report_public_base_url_missing`. Do not return an internal path to Feishu.

## HTML sections

The HTML report must include at least:

1. Report header: hotel, period, generated time, freshness.
2. Overall conclusion: third-party score, demand impact, opportunity level, risk level.
3. Local events: name, type, time, distance, impacted room type, demand impact, confidence.
4. Weather impact: condition, temperature, rain or extreme weather, impact on stay and e-sports room demand.
5. Holiday and workday context: holiday, weekend, adjusted workday, demand impact.
6. OTA actions: price, promotion, inventory, room-type focus.
7. Data gaps: missing sources, plugins to improve, confidence impact.
8. Action checklist: today, tonight, tomorrow.

## Feishu card contract

The Feishu card must include:

```text
Title: S14-EXT 第三方环境诊断报告已生成
Hotel: 星锋电竞酒店
Period: 2026-06-29
Summary: 中等机会 / 低风险
Button: 查看完整诊断报告
```

The button URL must equal `report_url`.

The Feishu card must not expose:

```text
report_file_path
/opt/
/etc/
workspace internal path
raw collector config
secret, token, DSN, password
```

## File name rule

Use a unique filename per report:

```text
s14_ext_report_{hotel_id}_{yyyyMMddHHmmss}_{short_hash}.html
```

Do not send a `latest` URL to Feishu. A `latest` copy may exist for debugging, but Feishu must point to the unique run URL.

## Static serving

Only expose `public/s14-reports/`, not the whole workspace.

Example Nginx block:

```nginx
location /s14-reports/ {
    alias /opt/openclaw/workspaces/hotel-ota-ai/public/s14-reports/;
    add_header Cache-Control "no-store";
    autoindex off;
}
```
