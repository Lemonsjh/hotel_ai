## Design

### Schema

新增表：

```sql
chat_role_memberships(
  chat_id_hash TEXT NOT NULL,
  hotel_id TEXT NOT NULL,
  principal_id TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(chat_id_hash, hotel_id, principal_id)
)
```

只保存 `chat_id_hash`，不保存原始 `chat_id`。

### ROLE confirmation

`confirm_chat_role_change_request()` 已经校验 `request_chat_hash` 与当前 `chat_id` 匹配。确认通过后：

- `grant` 写入/更新 `chat_role_memberships`
- `revoke` 只撤销当前 `chat_id_hash + hotel_id + principal_id`
- 不再把群聊角色写入 `hotel_memberships`

### Group auth

群聊 `_sqlite_auth_context()` 解析出 principal 和绑定酒店后：

1. global admin 仍然全局 admin。
2. 查 `chat_role_memberships` 的当前群角色，命中则使用它，`tenant_status=chat_role_bound`。
3. 未命中时查 `hotel_memberships`，只把它视作私有配置的酒店级基础权限，`tenant_status=hotel_membership_fallback`。
4. 都没有则 fail closed。

### Read model

`build_tenant_management_read_model()` 新增可选 `chat_id`。传入时只统计当前群的 `chat_role_memberships`，并返回 `role_scope=current_chat`。未传入时保留酒店级汇总语义。
