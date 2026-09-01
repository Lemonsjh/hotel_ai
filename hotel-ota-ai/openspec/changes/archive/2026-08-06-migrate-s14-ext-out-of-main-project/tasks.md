## 1. Spec

- [x] 1.1 编写 S14-EXT 迁出主项目 OpenSpec。
- [x] 1.2 通过 `openspec validate migrate-s14-ext-out-of-main-project --strict`。

## 2. Tests

- [x] 2.1 增加飞书路由触发第三方诊断返回迁出提示测试。
- [x] 2.2 增加 `s14-ext-diagnosis` CLI 废弃提示测试。

## 3. Implementation

- [x] 3.1 移除主飞书路由对 S14-EXT 模块的直接 import 和调用。
- [x] 3.2 废弃主项目 `s14-ext-diagnosis` CLI 生成报告能力。
- [x] 3.3 保留当前酒店 S14 诊断不受影响。

## 4. Verification

- [x] 4.1 运行相关测试。
- [x] 4.2 运行 grep、OpenSpec validate 和 diff 检查。
