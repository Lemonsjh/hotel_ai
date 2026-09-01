# OpenClaw Windows 工作区部署说明

本目录保存本机 OpenClaw 使用的工作区。当前包含两个项目：

- `hotel-ota-ai`：酒店 OTA 数字员工与飞书机器人运行时。
- `ota-marketing-diagnosis`：OTA 营销诊断工作区。

## 用途

本 README 可随本目录上传到独立的 **私有** GitHub 部署仓库，用于说明 Windows 本机部署结构。代码的最终事实源仍应是各项目的正式代码仓库；本目录只作为部署后的工作区副本。

## 上传前必须排除

不得提交任何密钥、生产数据或运行产物。至少应在部署仓库的 `.gitignore` 中忽略：

```gitignore
# 私有环境与密钥
**/.env
**/*.env
!**/*.env.example
**/*secret*
**/*credential*

# 数据库、状态与运行产物
**/state/
**/*.sqlite
**/*.sqlite3
**/logs/
**/reports/
**/cache/
**/__pycache__/
**/*.pyc

# OpenClaw 本机状态
.openclaw/
```

私有配置、SQLite 状态库、日志和报告应保留在 `C:\ProgramData\hotel-ota-ai\` 或本机 OpenClaw 状态目录，不能上传。

## 推荐同步流程

1. 先将工作区中需要保留的代码改动合并并提交到正式项目代码仓库。
2. 部署仓库只维护 Windows 安装脚本、配置模板、版本说明及本 README。
3. 新电脑部署时，从正式代码仓库检出固定提交，再填入本机私有环境变量和配置文件。
4. 不从另一台电脑直接复制 `state`、`.env` 或 OpenClaw 网关状态。

## 部署验证

完成配置后，确认：

- 网关能正常启动；
- 飞书机器人能收到并回复消息；
- 业务查询使用绑定酒店的真实数据源；
- 写入类能力仍经过相应的审批与安全闸门。
