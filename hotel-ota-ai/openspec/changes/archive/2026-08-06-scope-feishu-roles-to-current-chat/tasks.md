## 1. Red tests

- [x] 1.1 同酒店两个 chat_id 的当前群角色查询互相隔离。
- [x] 1.2 群 A owner 不会在群 B 自动获得 owner。
- [x] 1.3 ROLE 确认写入群级 membership，不泄露 raw open_id。

## 2. Implementation

- [x] 2.1 新增 `chat_role_memberships` schema。
- [x] 2.2 ROLE 确认写入/撤销当前群级 membership。
- [x] 2.3 群聊鉴权优先查当前群级 role。
- [x] 2.4 当前群管理读模型按 `chat_id_hash` 过滤。

## 3. Verification

- [x] 3.1 `openspec validate scope-feishu-roles-to-current-chat --strict` 通过。
- [x] 3.2 飞书/安全相关测试通过。
