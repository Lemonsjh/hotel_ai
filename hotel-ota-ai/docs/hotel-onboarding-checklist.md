# 多酒店接入清单

每个酒店必须使用唯一的 `hotel_id`，并新增一对飞书机器人（chief + S14）。不要复制或共用其他酒店的群绑定、成员角色或酒店身份映射。

1. 在 SQLite Active Auth 通过 BIND / ROLE 建立群绑定和成员角色。
2. 在 `database-source.json` 建立 `hotel_id -> *_mysql_prod` profile；子 profile 可以继承表/字段，但必须显式声明自己的 `hotel_ids`。
3. 在私有环境文件配置 `HOTEL_OTA_DB_DSN_<HOTEL>`、`S14_DB_DSN_<HOTEL>` 及三类精确写入 DSN。三类写入 DSN 可指向同一物理库，但必须是该酒店的写入账号。
4. 在 OpenClaw 配置两账号和精确群 allowlist；chief 加入 `bot_account_hotel_map`，S14 加入 `s14-account-map.json`。
5. 配置 S14 源、市场源和需要的任务表后，重载服务。
6. 运行：`python3 scripts/validate_hotel_onboarding.py --hotel-id <id> --chief-account <chief> --s14-account <s14>`。只有 required 项全通过才允许接入生产群。

缺少市场源或某类写入 DSN 时，该能力必须保持 fail-closed；不得回退到其他酒店。
