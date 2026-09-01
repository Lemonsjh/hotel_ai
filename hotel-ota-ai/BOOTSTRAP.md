# OpenClaw Workspace Bootstrap

本文件只负责说明 workspace 启动读取顺序。项目运行、安全、数据、调价和输出边界以 `AGENTS.md` 为准；普通飞书菜单以 `MENU.md` 为唯一事实源；S15/S16 的 AI 最终回复还必须遵守 `S15_S16_AI_OUTPUT.md`。

生产飞书禁止 demo/sample/synthetic/static fallback；私聊可通过 `open_id/user_id/union_id -> auth_principals -> hotel_memberships` 授权，但 `user:ou_*` 仍只是发送目标，不是业务 `chat_id`。

飞书运行时鉴权优先级为 SQLite Active Auth，其次才是 JSON bootstrap/emergency fallback。不要只查 `/etc/hotel-ota-ai/feishu-role-map.json` 后判断权限。

**每次飞书业务查询都要带上网关可信身份（`feishu-route --production-feishu` + 本条消息的 `chat_id` + `open_id`）**，缺了就会 fail-closed 降级 guest（`HOTEL_OTA_REQUIRE_VERIFIED_ROLE=1`）→ 误报"群未绑定/guest"。遇到意外的未绑定/guest，先自查是否漏传鉴权、带上重试，**不得把降级结果当事实报给用户**。

**owner 权限口径必须与 runtime 一致。** `owner` 具有 `manage_roles`，可在当前绑定酒店内通过 ROLE 流程直接把其他 `owner/operator/frontdesk` 改为任一酒店成员角色；包括 `owner -> operator/frontdesk`，不需要先 revoke 再 grant。owner 不得修改自己、不得修改 `admin`、不得跨酒店操作。owner 发起的 ROLE 请求允许由该发起 owner 自己发送 `确认 ROLE-...` 完成确认，不要求第二位 owner/admin；operator 发起的申请仍必须由 owner/admin 确认。回答「我的权限有哪些」时，这项必须列在 owner 的可用权限中，不能笼统写成“admin 专属”。只有跨酒店/全局管理员范围的角色管理、安全配置和紧急停用仍属于 admin 边界。

**ROLE 身份说明禁止模型猜测。** 发起人、目标成员、确认人/approver 的姓名和角色只能使用 ROLE runtime 返回的 `role_change_identity`，其事实源必须是 `sqlite_active_auth`；如果 runtime 没有返回对应姓名，只能说“身份名称未解析”，不得根据历史聊天、成员列表顺序、昵称记忆或上下文猜一个确认人。尤其不得把 requester 当 approver，也不得把其他 owner 的名字套到实际确认人上。

数据库历史表不要求一次性补齐 `hotel_id` / `room_type_id`，但必须通过 normalized query layer 兼容读取。映射表是统一房型与平台商品身份事实源；`hotel_name` legacy fallback 只读。当前生产调价只使用 active `mapping_status=AUTO` 映射；`CONFIRMED` 及其他状态不可用于 S5/S6，`match_rule` 不作为写入前置条件。名称反推仍只用于 preview/诊断并标 `inferred_by_name`，不得写入价格任务。

**S14 主运营诊断已从生产飞书彻底停用。** `s14`、`S14诊断`、`OTA运营诊断`、`综合诊断/综合运营诊断` 等旧入口不得再运行 S14，也不得出现在菜单中。收到这些请求时，只能按当前可信 `chat_id` 查询 `/etc/hotel-ota-ai/diagnosis-bot-map.json`（或 `HOTEL_OTA_DIAGNOSIS_BOT_CONFIG` 指定的私有映射）：若该群明确配置了 active 独立综合诊断机器人，则回复“请在本群 @该机器人并发送综合诊断”；若没有 exact chat 映射，则必须明确回复“当前群未配置独立综合诊断机器人”，不得猜机器人名称。S14-EXT 第三方报告仍是独立服务边界，不得回落到主 S14。

S15 只使用可复现的真实历史分时批次生成 24 小时容量节奏与参考完成节奏；缺失小时必须标记采集覆盖缺口，不允许再用默认累计比例锚点补造。S16 使用已物化的 S15 基准和 `pms_room_type_forecast` 当前完整房型批次，不依赖 S2 输出，也不使用 `jd01/jd04/kf11` 重新拼接承诺已售。

## 控制面 Fast Path（先于 Skill-first）

每条生产飞书消息在读取 `router/skill_route_index.md`、S1 Skill 或任何 Scenario 之前，先判断是否属于确定性的控制面写操作。以下请求命中后必须立即进入 `feishu-route`，不再做普通 Skill 查找：

- 任命、授予某人为 `owner/operator/frontdesk`；
- 将/把某人直接改成、换成、设为 `owner/operator/frontdesk`；
- 撤销某人的酒店角色/身份；
- `确认 ROLE-*`、`取消 ROLE-*`；
- BIND / CFG 的申请、确认和取消。

命中控制面 Fast Path 时：

1. 不读取 `router/skill_route_index.md`；
2. 不加载 `skills/hotel-ota/s01-control-config/SKILL.md` 及其 references；
3. 不搜索其他 Skill 或 Scenario；
4. 直接携带本条消息的可信 `chat_id` 和 `open_id/user_id/union_id` 调用 `python runtime/hotel_ota_runtime.py feishu-route --production-feishu ...`；
5. 以 runtime 的鉴权、ROLE/BIND/CFG 状态和身份事实作为唯一执行结果，再组织简短回复。

`我的权限是什么`、`owner 能不能任命前台`、`当前酒店有哪些角色` 等查询/解释不属于控制面写 Fast Path，可继续进入 S1 或对应只读控制面查询。Fast Path 只减少工具发现和文档读取，不改变 SQLite Active Auth、权限闸门、ROLE 二次确认、owner 自确认或审计规则。

## 普通飞书业务读取顺序

未命中上述控制面 Fast Path 的普通自然语言业务问答优先采用 Skill-first，避免在尚未确定主问题时预加载全部 Scenario：

1. `AGENTS.md`：只先确认鉴权、安全、数据真实性和执行边界；其中关于 S14 可独立运行的旧描述不得使用。
2. 如果用户请求「菜单 / 能力菜单」，直接读取并发送 `MENU.md`，不得根据 Skill 列表、Scenario、历史聊天或模型记忆重建菜单；菜单请求到此结束。
3. `router/skill_route_index.md`：确定唯一主 Skill；普通自然语言 ownership 以该索引为准。
4. 命中的 `skills/hotel-ota/<skill>/SKILL.md`。
5. 只读取该 Skill 当前任务真正需要的 `references/`；S15/S16 还必须遵守 `S15_S16_AI_OUTPUT.md`。
6. 调用受控 runtime，并以 runtime 返回作为业务事实源。

一旦普通问题已经确定唯一主 Skill，不得再因为辅助证据词重新搜索 Scenario 或其他 Skill。Skill 按 `config/skill-dependencies.yaml` 读取确定性依赖不属于重新路由。

**单事实查询采用 20 秒响应预算。** 如果用户只问一个明确金额、数量、比例、状态、排名或时间点，例如“今天推广花了多少钱”“当前出租率多少”“还有多少待回复评论”，先让主 Skill 做一次受控读取或固定源能力检查。主 Skill 已能回答就立即返回；若它明确缺字段、缺时间粒度或没有对应事实，可以在当前酒店范围内尝试一次受控只读 SQL factual fallback，但不得切换其他 Skill/Scenario 去凑答案。

受控 factual fallback 的执行入口是 `python -m runtime.sql_fact_query --hotel-id <hotel_id> --sql '<SELECT ... WHERE hotel_id = :hotel_id>'`。该入口只允许单表、单条、酒店范围内的 `SELECT`，禁止写操作、跨酒店、敏感字段、JOIN/UNION/子查询等危险或复杂形态，并且单次 MySQL 查询硬限制为 **20 秒**。现有 `database-query --sql` 仍然保持禁止，不得绕过。

**20 秒内不能形成可靠答案时，必须结束当前请求。** 不再继续读取其他 Skill、Scenario、历史文档或无限尝试工具，而是直接回复：`这个问题需要进一步查询业务数据库，可能会比普通查询慢一些。回复「继续查询」我再继续。` 这不是后台任务；回复后当前轮已经结束，禁止说“正在后台查询”“请稍等”或暗示系统仍在继续运行。

用户在同一飞书对话中回复 `继续查询` 时，使用当前对话上下文恢复上一条待深入查询的问题和酒店范围，再执行受控深入查询；如果上下文中没有明确的上一条待续查问题，不得猜测。第二阶段查询仍必须有界，查询失败、数据不存在或仍无法形成可靠结论时直接说明缺口并结束，不得再次无限漫游。

**factual fallback 只能补事实，不能补算法。** “该不该调价”“为什么卖得慢”“推广值不值得继续”“帮我执行/审批/修改配置”等决策、诊断、建议和动作必须继续服从 S5/S16/S10/S6/S1 等正式能力，不能因为 native data gap 就让通用 SQL 自己重新推导业务结论。S14 主能力同样禁止通过 SQL fallback 恢复或拼装。

只有用户明确要求“完整、综合、全盘、一起分析、一整套、完整经营分析”等多能力流程，或任务本身是 cron/工作流时，才继续读取：

1. `router/scenario_router.yaml`
2. `architecture/scenario_chain_registry.json`
3. 对应 Scenario 所需的 Skill 和受控依赖

即使进入 Scenario，也不得把 S14 主能力恢复为可调用节点；需要的事实和判断应由仍在使用的单项能力提供。对于“综合诊断”这个已经明确退役并转交独立机器人的入口，优先执行上面的独立机器人 handoff，不在本机器人内重新拼装一个 S14 替代品。

## 定时任务 / cron 请求

用户要求创建、修改、删除、查询或解释定时任务时，必须先读取 `SCHEDULED_TASK_POLICY.md`。尤其是飞书群定时推送，必须先确认本条消息的可信 `chat_id` 和当前群实际使用的 Feishu bot/app/account，再执行真实 scheduler 写操作并 read-back；无法查询 scheduler 或无法确定投递机器人时，必须明确说“尚未变更/无法确认”，不得声称“已创建”“已调好”“已执行”“已切换账号”。

## 开发、合同核验和架构任务

开发、测试、合同核验或架构修改时，再按任务需要读取：

- `TOOLS.md`
- `README.md`
- `contracts/v27/contract.json`
- `contracts/v27/field_registry.yaml`
- `contracts/v27/node_io_contract.yaml`
- `architecture/agent_registry.json`
- `architecture/node_registry.json`
- `architecture/scenario_chain_registry.json`
- `router/scenario_router.yaml`
- 当前 Skill 的 `references/v27_alignment.json`

这些文件仍是工程和合同事实源，但普通单 Skill 飞书问答不需要在确定 owner 之前全部预加载。

## 辅助文件边界

`USER.md`、`IDENTITY.md`、`SOUL.md`、`HEARTBEAT.md`、`MEMORY.md` 只作为初始化辅助。它们不得覆盖 runtime 返回结果、V27 contract、测试结果和 `AGENTS.md` 中的根级安全规则，也不得恢复已停用的 S14 主入口或自行扩充 `MENU.md`。

## 工作方式

- 先确认当前任务属于开发、测试、本地演示还是生产飞书链路。
- 开发和测试可以使用本地 demo 命令，但必须保留 demo 标记。
- 生产链路只接受 runtime 和受控数据源返回的事实。
- 修改代码后必须说明改了哪些文件、为什么改、怎么验证。