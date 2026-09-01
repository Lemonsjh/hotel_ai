## 1. Red tests

- [x] 1.1 identity 文本不包含 demo/sample/live/formal approval 环境判断。
- [x] 1.2 identity 文本包含“只检查身份和群绑定，不读取经营数据”说明。

## 2. Implementation

- [x] 2.1 调整 `identity` route summary。
- [x] 2.2 调整 `feishu_output_renderer` identity 文案。

## 3. Verification

- [x] 3.1 `openspec validate separate-identity-from-data-source-status --strict` 通过。
- [x] 3.2 飞书 identity 相关测试通过。
