# 酒店 OTA AI 数字员工 OpenClaw 工程包

这是可同步到阿里服务器 OpenClaw workspace 的酒店 OTA 数字员工工程包。

## 当前工程定位

当前项目以 `contracts/v27/contract.json` 和 runtime 返回结果为事实源，目标是形成生产闭环：

```text
飞书生产入口
-> 身份和酒店范围校验
-> PMS/OTA 真实数据按 hotel_id 流转
-> skill 自动补依赖
-> S14 / S14-EXT 报告
-> 调价任务审查、插件执行、平台回查
-> 飞书安全输出
```

当前运行形态是单总控 OpenClaw runtime + A0-A6 逻辑 Agent 分层，不是多个独立机器人实例。

## 当前运行入口

- `AGENTS.md`：根级运行、安全、数据和调价闭环规则。
- `BOOTSTRAP.md`：workspace 启动读取顺序。
- `TOOLS.md`：runtime 命令入口和本地验证命令。
- `runtime/hotel_ota_runtime.py`：CLI 兼容入口，负责 env-check、demo、Feishu route、dry-run、审批预览和安全校验。
- `contracts/v27/contract.json`：当前唯一 machine-readable 工程契约。
- `architecture/`、`router/`、`agents/`：V27 派生的节点、边、场景、路由和 Agent 边界。
- `skills/hotel-ota/`：17 个核心 skill 与 `S14-EXT` 扩展 skill。
- `config/`、`cron/`、`ops/`、`manifests/`：配置样例、定时任务、运维和清单边界。

`USER.md`、`IDENTITY.md`、`SOUL.md`、`HEARTBEAT.md`、`MEMORY.md` 是 workspace 初始化辅助文件，不是权限来源、业务数据来源或审批依据。

## 服务器部署位置

默认 workspace：

```bash
/opt/openclaw/workspaces/hotel-ota-ai
```

更新或部署前按以下当前入口执行，不再使用旧 `requirements/` 教程：

1. 阅读 `ops/server-update-guide.md`，先备份 workspace 和私有配置元数据。
2. 核对 `manifests/deploy_manifest.yaml` 与 `manifests/runtime_manifest.yaml` 的交付边界。
3. 运行 V27 契约、compileall 和聚焦/全量测试，再按已安装 OpenClaw 版本支持的流程应用配置补丁。
4. `/etc/hotel-ota-ai/` 与 Git 分离，严禁覆盖或提交真实密钥、身份、DSN、token 和数据库映射。

## 生产数据主链路

- 生产酒店 ID 必须来自已验证的 runtime auth context、tenant config、数据库配置或受控 alias registry。
- 酒店展示名、平台名、legacy alias 与 `hotel_id` 的关系不得写死在根说明文件里；应由私有配置、数据库映射或租户 alias registry 管理。
- demo 酒店 ID 与生产酒店 ID 必须明确隔离，生产飞书不可回退到 demo 酒店。
- 生产查询优先 `hotel_id`；`hotel_name` 只用于展示或 legacy fallback。
- 表、字段或数据缺失时返回 `data_gap` / `schema_drift`，不得跨酒店借数。

MySQL 数据库通过 `/etc/hotel-ota-ai/database-source.json` 配置化接入。字段、表或库变化时优先修改私有 mapping profile，不修改 17 个 skill。`guest_name`、`room_no`、`order_id`、`operator_name`、`product_cipher` 默认脱敏。

生产试运行前必须先跑 `database-inspect --mode tables` 做只读表结构检查。当前 `hotel_puyue` 生产试验库按 27 表模板接入，其中 `meituan_ota_nearby_event` 可作为周边活动上下文；PMS 历史表如存在空 `hotel_id`，可通过 `hotel_room_type_mapping` 中相同 `hotel_name` 受控补齐酒店范围。缺统一 `room_type_id`、缺 `source_product_id/product_cipher`、映射未确认或字段为空时，相关功能必须降级为 `data_gap`、`schema_drift`、`mapping_pending`、`preview_only` 或 `disabled_until_data_ready`。

兼容查询层位于 `runtime/adapters/normalized_query.py`。它允许历史表暂时保留原结构：有 `hotel_id` 时按 `hotel_id` 过滤；`hotel_id` 为空但 `hotel_name` 可由 `hotel_room_type_mapping` 受控反推出酒店时，只做只读 legacy 诊断并内部标记风险；房型和平台商品身份必须由映射表确认。平台字段为空时按散客 `walkin` 处理。S5/S6 price task 只能使用 active `mapping_status=AUTO` 映射；`CONFIRMED` 和 `match_rule` 均不能替代 AUTO 放行，名称反推只用于 preview/诊断。

飞书运行时鉴权优先读取 SQLite Active Auth（`auth_principals`、`hotel_memberships`、`chat_bindings/group_chat_bindings`）。`/etc/hotel-ota-ai/feishu-role-map.json` 只用于 bootstrap、global admin 声明和 emergency fallback，不是日常运行时优先事实源。

S14-EXT 注册 Excel 源可通过 `s14 source=monthly_excel` 触发，报告目录由 `HOTEL_OTA_S14_REPORT_DIR` 指定，公开链接前缀由 `HOTEL_OTA_S14_REPORT_BASE_URL` 指定。未配置 BASE_URL 时只生成本地 HTML；飞书只展示 `report_url`，不展示本地路径。若要用 Nginx 暴露报告，可人工配置：

```nginx
server {
    listen 8081;
    location /reports/ {
        alias /var/lib/hotel-ota-ai/s14/reports/;
        autoindex off;
    }
}
```

S15 销售基准线只使用可复现的真实历史分时批次生成小时目标曲线。缺失小时保留缺口并标记采集覆盖不足，不使用默认累计比例或默认锚点补造生产事实。

## Demo 与生产边界

本地开发可以运行：

```bash
python runtime/hotel_ota_runtime.py --demo demo-chain --all
python runtime/hotel_ota_runtime.py --demo demo-node --all
python runtime/hotel_ota_runtime.py generate-today-demo --write-db
```

所有 demo 输出必须保持 `data_source_type=demo_data` 或清楚标注 `context_source`，并且不得创建正式审批或 live 写入。

生产飞书通道不使用 demo、sample、synthetic 或 static fixtures 生成正式业务结论；缺真实数据返回 `data_gap`。

## 调价任务闭环

S5 只给收益建议。S6 进入任务链路前必须经过 dry-run、数据新鲜度、价格护栏和人工确认。

`execute_status=PENDING/SUCCESS/FAILED` 保留为旧插件 outbox 兼容状态。完整闭环需要额外记录：

```text
review_status
plugin_status
verification_status
approved_at
queued_at
plugin_picked_at
executed_at
verified_at
platform_actual_price
```

旧 `*_ENABLE_LIVE` 直连 API 开关是 deprecated 诊断项，不能作为当前生产调价路径。

## 开发与运行边界

- 运行必需文件见 `manifests/runtime_manifest.yaml`。
- 部署包边界见 `manifests/deploy_manifest.yaml`。
- 开发资料边界见 `manifests/dev_docs_manifest.yaml`。
- 文档上下文边界见 `manifests/docs_context_manifest.yaml`。
- V27 工程契约事实源见 `contracts/v27/contract.json`。
- Skill 规则见 `skills/hotel-ota/*/references/`。
- 运行安全与 demo mode 见 `runtime/demo_mode.py`、`runtime/data_gate.py`。

普通飞书输出必须经过 `feishu-output-gate`，不得暴露私有路径、真实身份 ID、DSN、token、role-map、完整 runtime JSON、原始表结构或 API request body。
