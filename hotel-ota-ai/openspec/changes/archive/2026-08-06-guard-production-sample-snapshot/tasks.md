## 1. Spec

- [x] 1.1 编写 production sample guard OpenSpec。
- [x] 1.2 通过 `openspec validate guard-production-sample-snapshot --strict`。

## 2. Tests

- [x] 2.1 增加生产 Feishu / decision 路径回归测试，证明缺真实数据时返回 `data_gap`。
- [x] 2.2 测试输出不包含 `170`、`107`、`5.74`、`58`、`sample_data`、`demo_data` 作为业务证据。

## 3. Implementation

- [x] 3.1 将 sample snapshot 明确限定为 demo/local helper。
- [x] 3.2 修复 production Feishu 可达路径，缺真实数据时返回 `data_gap`。

## 4. Verification

- [x] 4.1 运行相关单元测试。
- [x] 4.2 运行 grep 检查和 git 状态检查。
