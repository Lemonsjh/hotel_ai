-- Hotel OTA AI zhiting price task outbox.
-- Additive MySQL DDL for production trial. Review and run manually against the
-- configured business database. This file does not contain credentials.

CREATE TABLE IF NOT EXISTS meituan_ota_goods_price_mapping (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  hotel_name VARCHAR(128) NULL,
  channel_source VARCHAR(32) NOT NULL DEFAULT 'meituan',
  room_type_name VARCHAR(128) NOT NULL,
  business_date DATE NOT NULL,
  ota_product_id VARCHAR(128) NOT NULL,
  ota_product_name VARCHAR(255) NULL,
  ota_sale_price DECIMAL(10,2) NULL,
  commission_rate DECIMAL(8,4) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_meituan_mapping_product_date (ota_product_id, business_date),
  KEY idx_meituan_mapping_room_date (hotel_name, room_type_name, business_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ctrip_ota_goods_price_mapping (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  hotel_name VARCHAR(128) NULL,
  channel_source VARCHAR(32) NOT NULL DEFAULT 'ctrip',
  room_type_name VARCHAR(128) NOT NULL,
  business_date DATE NOT NULL,
  ota_product_id VARCHAR(128) NOT NULL,
  ota_product_name VARCHAR(255) NULL,
  product_cipher VARCHAR(255) NULL,
  price_editable_flag TINYINT(1) NOT NULL DEFAULT 0,
  ota_sale_price DECIMAL(10,2) NULL,
  commission_rate DECIMAL(8,4) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ctrip_mapping_product_date (ota_product_id, business_date),
  KEY idx_ctrip_mapping_room_date (hotel_name, room_type_name, business_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS meituan_zhiting_price_task (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  hotel_name VARCHAR(128) NULL,
  ota_product_id VARCHAR(128) NOT NULL,
  room_type_name VARCHAR(128) NOT NULL,
  business_date DATE NOT NULL COMMENT 'Sale/stay business date, not task creation date.',
  target_sale_price DECIMAL(10,2) NOT NULL,
  execute_status ENUM('PENDING','SUCCESS','FAILED') NOT NULL DEFAULT 'PENDING',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  source_decision_id VARCHAR(128) NULL,
  created_by VARCHAR(128) NULL,
  error_message VARCHAR(512) NULL,
  executed_at DATETIME NULL,
  KEY idx_meituan_task_pending (execute_status, business_date, ota_product_id),
  KEY idx_meituan_task_decision (source_decision_id),
  UNIQUE KEY uq_meituan_pending_product_date (ota_product_id, business_date, execute_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ctrip_zhiting_price_task (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  hotel_name VARCHAR(128) NULL,
  ota_product_id VARCHAR(128) NOT NULL,
  room_type_name VARCHAR(128) NOT NULL,
  business_date DATE NOT NULL COMMENT 'Sale/stay business date, not task creation date.',
  target_sale_price DECIMAL(10,2) NOT NULL,
  execute_status ENUM('PENDING','SUCCESS','FAILED') NOT NULL DEFAULT 'PENDING',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  product_cipher VARCHAR(255) NOT NULL,
  source_decision_id VARCHAR(128) NULL,
  created_by VARCHAR(128) NULL,
  error_message VARCHAR(512) NULL,
  executed_at DATETIME NULL,
  KEY idx_ctrip_task_pending (execute_status, business_date, ota_product_id),
  KEY idx_ctrip_task_decision (source_decision_id),
  UNIQUE KEY uq_ctrip_pending_product_date (ota_product_id, business_date, execute_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

