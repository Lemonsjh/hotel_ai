## Why

价格护栏同时存在算法默认 YAML、SQLite active policy 和 Agent 口头说明。生产结果必须只来自可审计的 active policy，避免 S5、S6 和飞书查询口径漂移。

## What Changes

- 建立 active policy 为生产唯一护栏来源，缺失时返回明确默认来源。
- 让 S5、S6 和飞书查询消费同一解析结果。
- 限制 YAML 为算法/演示默认，不得作为当前生产配置说明。

## Impact

影响 control plane、S5/S6 handoff、Feishu management read model、模板和测试；不允许飞书直接修改任何配置。
