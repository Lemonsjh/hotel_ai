## 1. 生产 demo gate

- [x] 1.1 验证显式 `demo` / `演示` 在 `production_feishu=True` 下 blocked。
- [x] 1.2 验证 `*-demo` hotel id 在生产飞书下 blocked。
- [x] 1.3 验证生产飞书缺真实数据时不返回 demo/sample/synthetic 数据。

## 2. 验收

- [x] 2.1 运行 OpenSpec strict validate。
- [x] 2.2 运行生产飞书 demo fallback 相关单元测试。
