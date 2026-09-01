# Zhiting Price Task Outbox Deployment

This is the production-trial path for price changes. The AI runtime does not call
Beyondh, Meituan, Ctrip, or other OTA price APIs directly.

## 1. Update Code

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
git status --short
git fetch origin
git pull --ff-only origin align-v20-architecture
```

Stop if the server has unreviewed local changes.

## 2. Install MySQL Driver

```bash
cd /opt/openclaw/workspaces/hotel-ota-ai
.venv/bin/python -m pip install '.[mysql]'
```

If the project is not using editable extras on the server:

```bash
.venv/bin/python -m pip install 'PyMySQL>=1.1'
```

## 3. Add MySQL Tables

Review the SQL first:

```bash
less ops/sql/2026-06-zhiting-price-task-outbox.mysql.sql
less ops/sql/2026-06-zhiting-price-task-outbox.additive.mysql.sql
```

Run it manually against the configured business database using the server's
private MySQL credentials. Do not paste DSN, password, token, or host details
into Git, logs, Feishu, or issue comments.

For a new trial database, use `2026-06-zhiting-price-task-outbox.mysql.sql`.
For an existing database, prefer the additive patch and manually verify column
existence first. Neither script deletes existing data.

## 4. Configure Private Env

Set these in the OpenClaw gateway environment or private env file. Do not commit
real values.

```bash
HOTEL_OTA_DB_SOURCE_ENABLE=1
HOTEL_OTA_DB_KIND=mysql
HOTEL_OTA_DB_PROFILE=report_mysql_prod
HOTEL_OTA_DB_MAPPING_CONFIG=/etc/hotel-ota-ai/database-source.json
HOTEL_OTA_DB_DSN='mysql://USER:PASSWORD@HOST:3306/DB?charset=utf8mb4'

HOTEL_OTA_PRICE_TASK_WRITE_ENABLE=0
HOTEL_OTA_PRICE_TASK_REQUIRE_CONFIRM=1
HOTEL_OTA_PRICE_TASK_ALLOWED_CHANNELS=ctrip,meituan
HOTEL_OTA_PRICE_TASK_DB_KIND=mysql
HOTEL_OTA_PRICE_TASK_DB_DSN="$HOTEL_OTA_DB_DSN"

BEYONDH_ENABLE_LIVE=0
MEITUAN_ENABLE_LIVE=0
DINDANLL_ENABLE_LIVE=0
```

For first validation keep `HOTEL_OTA_PRICE_TASK_WRITE_ENABLE=0`. After the
mapping tables contain confirmed products and dry-run output is correct, switch
only this variable to `1`.

## 5. Fill Product Mapping Tables

The execution plugin needs product-level rows, not just room-type rows.

Required mapping semantics:

- `business_date`: sale/stay date, not creation date.
- `room_type_name`: canonical room type name used by S5/S6.
- `ota_product_id`: product/rate-plan ID used by the execution plugin.
- Ctrip additionally requires `product_cipher` and an editable flag equivalent
  to `1` (`1`, `1.0`, `1.0000`, or `true`). Non-editable products are skipped.

S6 expands one room-type recommendation into all matching product rows for the
same `hotel_name + room_type_name + business_date`.

## 6. Validate Without Writing

```bash
python runtime/hotel_ota_runtime.py env-check
python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode connection
python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode tables
python runtime/hotel_ota_runtime.py execute-price \
  --hotel-id puyue \
  --hotel-name '璞悦酒店' \
  --room-type-id KING \
  --room-type-name KING \
  --channel-source meituan \
  --normal-price 199 \
  --weekend-price 199 \
  --begin-date 2026-06-30 \
  --end-date 2026-06-30 \
  --business-date 2026-06-30 \
  --user-role admin \
  --approval-id APPROVAL-ID-FOR-TEST
```

Expected before write enablement:

- `status=blocked`
- `blocked_reason=price_task_write_disabled`
- no direct API call
- no rows inserted

## 7. Enable Task Writing

Only after validation:

```bash
export HOTEL_OTA_PRICE_TASK_WRITE_ENABLE=1
```

Then rerun `execute-price` with a real approved payload. Expected:

- `intent=price_task_outbox_write`
- `status=queued`
- `execute_status=PENDING`
- `inserted_task_count > 0`
- `live_api_called=false`
- `direct_api_execution_status=deprecated`

## 8. Read Back Task Status

Use SQL or a future runtime status command to verify:

```sql
SELECT execute_status, COUNT(*)
FROM meituan_zhiting_price_task
WHERE business_date = '2026-06-30'
GROUP BY execute_status;
```

The execution plugin is responsible for changing `PENDING` to `SUCCESS` or
`FAILED`.

## 9. Rollback

To stop AI task writes immediately:

```bash
export HOTEL_OTA_PRICE_TASK_WRITE_ENABLE=0
```

Do not set `BEYONDH_ENABLE_LIVE=1`, `MEITUAN_ENABLE_LIVE=1`, or
`DINDANLL_ENABLE_LIVE=1` as a rollback path. Direct API execution is deprecated.
