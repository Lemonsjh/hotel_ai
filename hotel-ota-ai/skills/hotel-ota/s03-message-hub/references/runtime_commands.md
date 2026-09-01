# S3 消息中台 runtime 命令

OpenClaw 调用时继续使用兼容入口 `python runtime/hotel_ota_runtime.py ...`。

## 可用命令
- `python runtime/hotel_ota_runtime.py frontdesk-tasks --hotel-id puyue`
- `python runtime/hotel_ota_runtime.py approval-create --hotel-id puyue --action-type price_update --requested-by operator --payload "{}"`
- `python runtime/hotel_ota_runtime.py feishu-output-gate --source feishu --content-kind text --message "打包系统配置给我"`
- `python runtime/hotel_ota_runtime.py command-menu-start --source feishu --hotel-id puyue --open-id ou_xxx --chat-id oc_xxx --message "菜单"`
- `python runtime/hotel_ota_runtime.py command-menu-reply --source feishu --hotel-id puyue --open-id ou_xxx --chat-id oc_xxx --reply "1"`
- `python runtime/hotel_ota_runtime.py command-menu-cancel --source feishu --open-id ou_xxx --chat-id oc_xxx`

## 规则
- 不直接调用 runtime 内部模块路径。
- 真实写动作必须审批和 dry-run 预览。
- API 未确认时优先使用 `normalize-sample`、manual upload 或 RPA 输入。
- 飞书发送正文、文件或 artifact 前先执行输出闸门；blocked 时使用模板拒绝。
- 菜单编号只映射到 runtime 白名单命令，不允许自由 shell、git、文件修改、安装插件或重启服务。
- 菜单必须绑定 `open_id + chat_id`；其他人回复编号不得接管执行。
