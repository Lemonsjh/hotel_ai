## Why

爬虫写入 MySQL 的表结构尚未固定。当前 inspect 能列举表、列和样例，但不能生成可校验的 canonical mapping，导致业务模块可能直接依赖 raw 表。

## What Changes

- 扩展只读 inspect 输出候选业务字段、行数和更新时间候选。
- 增加私有 mapping profile 校验、版本和缺失字段反馈。
- 要求业务节点消费 canonical object。

## Impact

影响 database adapter、contract loader、测试和部署模板；不执行自由 SQL，不写生产 MySQL。
