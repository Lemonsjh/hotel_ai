## Why

`s14-ext-third-party-diagnosis` 已被业务决策为独立营销引流工具，不应继续挂在酒店 OTA 主项目飞书路由、主 CLI 或 admin/owner/operator 鉴权流程中。

## What Changes

- 主飞书路由中触发第三方营销诊断时，不再调用 S14-EXT adapter，而是返回迁移提示。
- 主项目 `s14-ext-diagnosis` CLI 废弃，不再生成第三方诊断报告。
- 移除主飞书路由对 `runtime.s14_ext_third_party_diagnosis` 的直接 import。
- 保留独立模块文件，供后续独立服务迁移或外部项目复用；主项目不再从飞书入口继续开发 Excel 上传/临时库营销报告逻辑。

## Impact

- 用户在主项目中触发第三方营销诊断会看到明确提示：“第三方营销诊断已迁移到独立服务，本项目不再处理该入口。”
- 当前酒店 OTA 主项目的 S14 当前酒店经营诊断不受影响。
- 历史独立模块测试可后续迁到独立服务；本 change 只封主项目入口。
