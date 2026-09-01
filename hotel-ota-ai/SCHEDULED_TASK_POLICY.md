# 飞书定时任务真实性与投递账号规则

本文件约束 OpenClaw 在酒店数字员工中创建、修改、删除、查询和解释定时任务。它不提供新的 scheduler 实现；它只规定在真实 scheduler 工具或运行记录不可用时必须 fail closed，禁止把计划、推测或聊天记忆说成已执行事实。

## 1. 创建或修改前必须先解析投递身份

涉及“每天几点发到本群”“定时推送到群里”“把某任务改成某个机器人发送”等请求时，落任务之前必须先确定：

1. 本条消息的可信 `chat_id` / conversation id；不得从正文猜群 ID。
2. 当前群实际接入并用于发送的 Feishu bot/app/account；不得直接继承 `default-*`、样例账号或其他群的机器人账号。
3. 目标酒店范围、时区、cron 表达式、timeout、任务名和 enabled 状态。
4. 如果 scheduler 把“执行账号”和“投递账号”分开配置，两者都必须读取真实当前值并显式核对。

任一项无法从可信运行上下文、scheduler 读接口或服务器私有配置中确认时，不得创建/修改并声称成功；必须明确返回“当前无法确定投递机器人/目标群，任务尚未变更”。

## 2. 写操作必须有真实返回和 read-back

只有真实 scheduler/create/update/delete 调用返回成功后，才能说“已创建”“已修改”“已删除”。写入后必须重新读取任务并核对至少：

- task id / task name
- cron 与 timezone
- timeout
- enabled
- delivery chat / conversation
- delivery bot/app/account（如果 scheduler 暴露）

只写了配置文件、只生成命令、只给出方案、只修改仓库脚本，都不能表述为服务器上的定时任务已经生效。

## 3. 运行状态和投递状态必须分开核对

要回答“今天执行了吗”“为什么没发”时，必须读取真实 scheduler run/history 和真实 delivery 结果：

- `execution=success` 只代表任务主体执行成功，不代表消息已送达。
- `delivery=success` 才能说明群消息已成功投递。
- 没有 run/history 证据时，不得编造“跑了 N 次”“前几次超时”“最后一次成功”。
- 没有 delivery/account 证据时，不得编造“因为 default bot 与当前群 bot 不一致”“已经切换到某账号”。

如果当前运行环境没有 scheduler 查询/修改工具，应直接说明“当前只能查看仓库静态 cron 定义，不能确认服务器实际任务或修改状态”，并停止事实性断言。

## 4. 仓库 cron 脚本边界

`cron/setup-cron.sh` 只是服务器人工安装本地 OpenClaw cron 的参考脚本，不是当前 scheduler 状态、run history 或飞书投递成功的事实源。脚本中的任务也不自动证明当前服务器已经安装。

S14 主能力已经退役，不得再安装 S14 定时任务。S2 群推送如果未来需要正式落地，必须在能够确认当前群 `chat_id` 和实际 Feishu bot/app/account 的 scheduler 路径中建立，不能靠模型口头声称创建。

## 5. 用户可见回复

定时任务回复必须区分以下三种状态：

- **已验证生效**：真实写调用成功 + read-back 一致。
- **已生成配置/命令但未验证生效**：仅仓库或计划层修改。
- **无法确认/尚未变更**：缺 scheduler、bot account、chat target 或 read-back。

禁止用“已调好 ✅”“已创建 ✅”“今天确实跑了”等确定性话术替代缺失的运行证据。
