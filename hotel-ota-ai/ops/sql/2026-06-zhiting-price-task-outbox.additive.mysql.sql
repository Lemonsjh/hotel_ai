-- Hotel OTA AI zhiting price task outbox additive patch.
-- MySQL 5.7/8.0 compatible column patch. Review manually before running.
-- This script contains no credentials and does not drop, truncate, or rewrite rows.
--
-- Prerequisite: the target tables already exist. For a new database, first run:
--   ops/sql/2026-06-zhiting-price-task-outbox.mysql.sql

DELIMITER $$

DROP PROCEDURE IF EXISTS hotel_ota_add_column_if_missing $$
CREATE PROCEDURE hotel_ota_add_column_if_missing(
  IN p_table_name VARCHAR(128),
  IN p_column_name VARCHAR(128),
  IN p_column_definition TEXT
)
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
  ) AND NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND column_name = p_column_name
  ) THEN
    SET @hotel_ota_sql = CONCAT(
      'ALTER TABLE `', REPLACE(p_table_name, '`', '``'),
      '` ADD COLUMN `', REPLACE(p_column_name, '`', '``'), '` ',
      p_column_definition
    );
    PREPARE hotel_ota_stmt FROM @hotel_ota_sql;
    EXECUTE hotel_ota_stmt;
    DEALLOCATE PREPARE hotel_ota_stmt;
  END IF;
END $$

DELIMITER ;

CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'hotel_name', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'channel_source', 'VARCHAR(32) NOT NULL DEFAULT ''meituan''');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'hotel_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'pms_room_type_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'pms_room_type_name', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'ota_room_type_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'room_type_name', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'business_date', 'DATE NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'ota_product_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'ota_product_name', 'VARCHAR(255) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'rate_plan_name', 'VARCHAR(255) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'is_super_deal', 'DECIMAL(8,4) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'ota_sale_price', 'DECIMAL(10,2) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'commission_rate', 'DECIMAL(8,4) NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'snapshot_time', 'DATETIME NULL');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'created_at', 'DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP');
CALL hotel_ota_add_column_if_missing('meituan_ota_goods_price_mapping', 'updated_at', 'DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP');

CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'hotel_name', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'channel_source', 'VARCHAR(32) NOT NULL DEFAULT ''ctrip''');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'hotel_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'ota_room_type_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'room_type_name', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'business_date', 'DATE NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'ota_product_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'ota_product_name', 'VARCHAR(255) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'product_cipher', 'VARCHAR(255) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'price_editable_flag', 'DECIMAL(8,4) NOT NULL DEFAULT 0');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'is_hour_room', 'DECIMAL(8,4) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'ota_sale_price', 'DECIMAL(10,2) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'commission_rate', 'DECIMAL(8,4) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'snapshot_time', 'DATETIME NULL');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'created_at', 'DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP');
CALL hotel_ota_add_column_if_missing('ctrip_ota_goods_price_mapping', 'updated_at', 'DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP');

CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'hotel_name', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'ota_product_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'room_type_name', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'business_date', 'DATE NULL COMMENT ''Sale/stay business date, not task creation date.''');
CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'target_sale_price', 'DECIMAL(10,2) NULL');
CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'execute_status', 'ENUM(''PENDING'',''SUCCESS'',''FAILED'') NOT NULL DEFAULT ''PENDING''');
CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'created_at', 'DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP');
CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'source_decision_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'created_by', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'error_message', 'VARCHAR(512) NULL');
CALL hotel_ota_add_column_if_missing('meituan_zhiting_price_task', 'executed_at', 'DATETIME NULL');

CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'hotel_name', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'ota_product_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'room_type_name', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'business_date', 'DATE NULL COMMENT ''Sale/stay business date, not task creation date.''');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'target_sale_price', 'DECIMAL(10,2) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'execute_status', 'ENUM(''PENDING'',''SUCCESS'',''FAILED'') NOT NULL DEFAULT ''PENDING''');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'created_at', 'DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'product_cipher', 'VARCHAR(255) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'source_decision_id', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'created_by', 'VARCHAR(128) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'error_message', 'VARCHAR(512) NULL');
CALL hotel_ota_add_column_if_missing('ctrip_zhiting_price_task', 'executed_at', 'DATETIME NULL');

DROP PROCEDURE IF EXISTS hotel_ota_add_column_if_missing;
