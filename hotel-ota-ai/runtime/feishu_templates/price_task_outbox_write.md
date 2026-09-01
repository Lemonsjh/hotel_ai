调价任务已写入任务表

- 渠道：{channel_source}
- 任务状态：{execute_status}
- 已写入任务数：{inserted_task_count}
- 展开产品数：{expanded_product_count}
- 跳过产品数：{skipped_product_count}
- 本次仅写入：立即返回，不等待插件处理或平台回查

边界：
- 当前不是 API 直连调价。
- 当前状态为 PENDING，等待独立执行插件拾取。
- 实际渠道调价、回读和异常处理仍以插件结果为准。
