## ADDED Requirements

### Requirement: S6 writes zhiting price task rows instead of direct OTA API calls
S6 production execution MUST create `PENDING` rows in the platform task table and MUST NOT call OTA/Beyondh/Meituan/Dindanll live APIs.

#### Scenario: Writing Meituan tasks
- **WHEN** an authorized admin or owner confirms a Meituan price update for a room type and business date
- **THEN** S6 expands the room type to all eligible `meituan_ota_goods_price_mapping` products
- **AND** writes one `PENDING` row per eligible product to `meituan_zhiting_price_task`
- **AND** includes `room_type_name`, `business_date`, `target_sale_price`, `source_decision_id`, `created_by`, and `created_at`

#### Scenario: Writing Ctrip tasks
- **WHEN** an authorized admin or owner confirms a Ctrip price update for a room type and business date
- **THEN** S6 expands the room type to all eligible `ctrip_ota_goods_price_mapping` products with `price_editable_flag=1`
- **AND** writes one `PENDING` row per eligible product to `ctrip_zhiting_price_task`
- **AND** includes `room_type_name` and `product_cipher`

### Requirement: Price task status is restricted
AI-created task rows MUST only use `execute_status=PENDING`; execution plugins are the only component allowed to update to `SUCCESS` or `FAILED`.

#### Scenario: AI creates a task
- **WHEN** S6 writes any zhiting price task row
- **THEN** `execute_status` is exactly `PENDING`
- **AND** unsupported states such as `AI_CREATED`, `RUNNING`, `CANCELLED`, `APPROVED`, or `CREATED` are rejected

#### Scenario: Plugin status readback
- **WHEN** runtime reads task status after plugin execution
- **THEN** it reports `SUCCESS` as plugin executed successfully
- **AND** reports `FAILED` with `error_message` and `executed_at`

### Requirement: Business date means sale/stay date
`business_date` in zhiting task rows MUST be the target sale/stay date, not the creation date.

#### Scenario: Future sale date task
- **WHEN** a task is created on `2026-06-26` for stay date `2026-06-30`
- **THEN** `business_date=2026-06-30`
- **AND** `created_at` records the creation timestamp

### Requirement: Duplicate pending tasks are skipped
S6 MUST NOT create duplicate pending tasks for the same platform product and business date.

#### Scenario: Pending task already exists
- **WHEN** a task table already contains `execute_status='PENDING'` for the same `ota_product_id` and `business_date`
- **THEN** S6 skips insertion for that product
- **AND** returns `duplicate_pending_task_skipped`

### Requirement: Task writes are gated by production controls
Task writes MUST be blocked unless task write is enabled, the channel is allowed, the user is authorized, the session is hotel-bound, the policy guard passes, and the request is confirmed.

#### Scenario: Write switch disabled
- **WHEN** `HOTEL_OTA_PRICE_TASK_WRITE_ENABLE` is not `1`
- **THEN** S6 returns preview only and does not insert task rows

#### Scenario: Direct API live path requested
- **WHEN** a caller attempts the old live adapter path
- **THEN** runtime returns `blocked_reason=direct_api_execution_deprecated_use_price_task_outbox`

### Requirement: Feishu output distinguishes task creation from OTA execution
Feishu replies MUST say that tasks were written for plugin processing and MUST NOT claim OTA price changes succeeded until readback shows `SUCCESS`.

#### Scenario: Task rows inserted
- **WHEN** S6 inserts `PENDING` task rows
- **THEN** the ordinary Feishu reply states platform, business date, room type, expanded product count, inserted task count, skipped product count, `PENDING`, source decision ID, and `live API not called`

#### Scenario: Task failed
- **WHEN** readback shows `FAILED`
- **THEN** Feishu shows the plugin failure reason and executed timestamp
