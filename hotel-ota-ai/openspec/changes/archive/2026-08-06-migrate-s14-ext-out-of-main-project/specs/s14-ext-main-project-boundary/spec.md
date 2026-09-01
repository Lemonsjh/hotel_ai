## ADDED Requirements

### Requirement: Main Feishu route must not process S14-EXT

The main hotel OTA Feishu route MUST NOT process third-party marketing diagnosis requests.

#### Scenario: User triggers third-party marketing diagnosis

- **WHEN** the main project Feishu router recognizes `third_party_report_preview` or `s14_source_request`
- **THEN** it returns a blocked/migrated result
- **AND** the summary says `第三方营销诊断已迁移到独立服务，本项目不再处理该入口。`
- **AND** no third-party report preview or Excel/MySQL diagnosis is generated

### Requirement: Main CLI S14-EXT command is deprecated

The main project CLI MUST NOT generate S14-EXT third-party marketing diagnosis reports.

#### Scenario: User runs s14-ext-diagnosis in main project

- **WHEN** `runtime.cli s14-ext-diagnosis` is invoked
- **THEN** the command returns a migrated/deprecated result
- **AND** it does not read Excel/MySQL input or generate a report
