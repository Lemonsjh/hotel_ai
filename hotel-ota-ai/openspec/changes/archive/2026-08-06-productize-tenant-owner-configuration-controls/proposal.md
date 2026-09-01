## Why

当前 V3 role-map、酒店范围鉴权和控制面基础能力已存在，但 Owner 不能在自己酒店内管理运营或前台成员；价格护栏仍以单一双向最大变动比例表示；飞书也缺少受控的管理查询入口。这使底层能力无法形成安全、可验证的产品流程。

## What Changes

- 允许 Owner 在自己已授权酒店内对其他既有 principal 的 `operator`、`frontdesk` 成员关系发起并一次确认授予或撤销；Owner 不得管理自己、Owner 或 admin。
- 将新价格护栏改为涨价/降价分别最小和最大变动比例，保留旧 `max_single_change_pct` 的只读兼容映射。
- 为飞书增加只读管理查询和平台无关的受控卡片预览/回调后端；不接入未经验证的 Feishu 原生 callback transport。
- 补齐迁移、插件 registry 排查和 Gateway 非 root 预检说明。

## Capabilities

### New Capabilities
- `owner-tenant-membership-control`: Owner scoped operator/frontdesk membership request and single confirmation.
- `directional-price-guard`: Four directional price guard thresholds with legacy read compatibility.
- `feishu-management-read-model`: Tenant-scoped, redacted management status and card preview contract.
- `owner-control-deployment-guidance`: V3 migration and plugin registry diagnostic guidance.

### Modified Capabilities
- `configuration-card-audit`: Applies the Owner single-confirmation exception only to scoped operator/frontdesk changes.
- `tenant-price-approval`: Binds directional policy values to formal approval and execution payload hashes.

## Impact

This change modifies control-plane validation, SQLite policy storage, price checks, payload hashes, Feishu intent routing, templates, tests, and deployment guidance. It never writes `/etc`, enables live execution, performs a channel write, or changes Gateway configuration.
