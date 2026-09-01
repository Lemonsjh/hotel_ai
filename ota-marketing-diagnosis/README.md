# OTA Marketing Diagnosis

独立的第三方 OTA 营销诊断工具。

它不属于 `hotel--ota-ai` 主项目。当前只保留最小可运行链路：

- 读取 Excel
- 读取阿里服务器本机 MySQL 诊断库
- 标准化字段
- 用代码计算指标
- 生成 `report.json`、`report.md` 和完整 `report.html`
- 通过 `skills/s14-operation-diagnosis` 挂载到 OpenClaw

数据库导出的 CSV/zip 只作为字段画像和开发参考，不作为正式产品入口，也不作为 CLI 运行入口。

## 当前保留的核心文件

```text
ota-marketing-diagnosis/
  marketing_diagnosis/
    main.py
    db_loader.py
    data.py
    metrics_core.py
    rules.py
    reporting.py
    excel_loader.py

  skills/
    s14-operation-diagnosis/
      openclaw.skill.yaml
      runtime/
        __init__.py
        feishu_adapter.py

  scripts/
    s14_feishu_entry.py
    create_sample_excel.py

  README.md
  requirements.txt
  setup.py
```

已删除未接入运行链路的触发词配置、schema 文档、runtime 命令文档、重复 router、SQLite 示例配置等脚手架文件。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## OpenClaw 挂载

推荐把本仓库作为独立 workspace 放到服务器：

```bash
cd /opt/openclaw/workspaces
git clone https://github.com/lijianlan1115-crypto/ota-marketing-diagnosis.git
cd ota-marketing-diagnosis
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 下载与同步

下载代码：

```bash
git clone https://github.com/lijianlan1115-crypto/ota-marketing-diagnosis.git
```

同步远程最新修改：

```bash
git pull origin main
```

修改后提交到自己有写入权限的仓库：

```bash
git add .
git commit -m '描述本次修改'
git push origin main
```

配置环境变量：

```bash
export S14_DB_DSN='mysql+pymysql://openclaw_user:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:3306/hotel_puyue?charset=utf8mb4'
export S14_REPORT_OUTPUT_DIR='/opt/openclaw/workspaces/ota-marketing-diagnosis/public/s14-reports'
export S14_PUBLIC_BASE_URL='http://47.108.200.194:8088/s14-reports'
```

OpenClaw 应识别：

```text
skills/s14-operation-diagnosis/openclaw.skill.yaml
```

如果先走飞书入口包装脚本，可调用：

```bash
python scripts/s14_feishu_entry.py --text 'S14诊断' --format text
```

通过 OpenClaw 的 shell/exec 工具调用时必须使用纯文本输出，避免卡片 JSON
被通道当作普通聊天内容。只有专用的结构化发送适配器才能使用
`--format card --raw-card-json`；适配器必须解析 JSON 后调用消息通道，
不得把 stdout 原样回复给用户。

数据来源按钮依赖飞书应用的卡片回调。回调未配置时保持
`S14_FEISHU_CARD_CALLBACK_ENABLED=0`，卡片只提示用户直接回复“数据库”或
“上传Excel”，不会展示无法点击的按钮。

当前 OpenClaw 飞书长连接负责接收普通消息，但不处理
`card.action.trigger`。飞书长连接采用集群随机投递，同一应用不能再启动一个
只处理卡片的长连接，否则事件可能被投递到错误的进程。S14 因此使用独立 HTTP
回调服务处理卡片点击，普通消息仍由 OpenClaw 长连接处理。

安装并启动回调服务：

```bash
pip install -e .
python scripts/s14_feishu_card_callback.py
```

生产环境可参考：

```text
deploy/systemd/s14-feishu-card-callback.service.example
deploy/nginx/s14-reports.conf.example
```

飞书后台的“回调配置”需要选择“将回调发送至开发者服务器”，请求地址指向：

```text
https://YOUR_PUBLIC_DOMAIN/s14/feishu/card-callback
```

并订阅、发布 `card.action.trigger`。服务端需要配置
`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_VERIFICATION_TOKEN`，如启用
加密还需配置 `FEISHU_ENCRYPT_KEY`。回调地址验证通过、服务启动后，才可设置：

```bash
export S14_FEISHU_CARD_CALLBACK_ENABLED=1
```

回调会在 3 秒内先返回中文提示，再异步生成报告并通过飞书消息 API 发送结构化
卡片。卡片 JSON、命令输出和异常堆栈只用于进程内部或服务器日志，不会作为聊天
消息发送给用户。

## 生成样例 Excel

```bash
python scripts/create_sample_excel.py
```

会生成：

```text
examples/sample_data.xlsx
```

## Excel 诊断

```bash
ota-marketing-diagnosis diagnose-excel --excel examples/sample_data.xlsx --output reports
```

也可以直接运行模块：

```bash
python -m marketing_diagnosis.main diagnose-excel --excel examples/sample_data.xlsx --output reports
```

Excel 支持以下 sheet：

| 标准 sheet | 说明 |
|---|---|
| `hotel_daily` | 每日经营数据 |
| `ota_funnel` | OTA 曝光、浏览、支付转化 |
| `products` | OTA 商品与价格梯度 |
| `reviews` | 公开评论与口碑 |
| `competitors` | 竞品价格、排名、活动标签 |

## 阿里服务器本机 MySQL 诊断

在服务器上设置 DSN：

```bash
export S14_DB_DSN='mysql+pymysql://openclaw_user:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:3306/hotel_puyue?charset=utf8mb4'
```

运行：

```bash
ota-marketing-diagnosis diagnose-db --dsn-env S14_DB_DSN --output reports
```

也可以直接传 DSN，但不建议把密码写进 shell 历史：

```bash
ota-marketing-diagnosis diagnose-db --dsn 'mysql+pymysql://user:password@127.0.0.1:3306/hotel_puyue?charset=utf8mb4' --output reports
```

`diagnose-db` 会按内置 `puyue_mysql_reference` profile 读取真实表并聚合成报告数据。报告里的“数据来源核验”章节会展示实际查到的表、行数、过滤条件和字段样本。

## 数据库画像参考

`yanglidata.zip` 这类数据库导出文件只用于确认真实表结构、真实字段名、空值情况和字段口径。它的结论会沉淀到数据库 profile、字段映射和聚合规则里，不会要求最终用户上传数据库导出包。

当前参考表包括：

- `jy01_hotel_statistics_daily`
- `rs01_room_revenue_daily`
- `jd01_booking_detail`
- `jd04_inhouse_extension`
- `kf11_room_status_snapshot`
- `meituan_ota_business_metrics` / `ctrip_ota_business_metrics`
- `meituan_ota_goods_price_mapping` / `ctrip_ota_goods_price_mapping`
- `meituan_ota_review_detail` / `ctrip_ota_review_detail`
- `meituan_ota_promotion_activity` / `ctrip_ota_promotion_activity`
- `meituan_ota_nearby_event`

## 项目边界

本项目只生成营销诊断报告，不做权限体系、调价写入、审批或线上执行。

公开 OTA 评论正文默认不脱敏，因为营销审核需要上下文。联系方式、订单号、房号、客人姓名等敏感字段会脱敏。

## 报告输出

```text
report.json
report.md
report.html
```

`report.html` 是完整可打开报告，包含总览、数据来源核验、M01-M08 评分、经营、OTA 漏斗、商品价格、口碑、竞品和数据质量章节。

HTML 采用绿色运营看板模板，展示规则计算结果和真实采集数据，不展示 AI 诊断分析。新生成的报告会自动使用当前模板。

如果需要把已有 demo 或旧报告替换为新模板，使用原有 `report.json` 重新渲染：

```bash
python scripts/render_report_html.py \
  --input /path/to/report.json \
  --output /path/to/report.html
```

在服务器更新已展示的页面：

```bash
cd /opt/openclaw/workspaces/ota-marketing-diagnosis
git pull origin main
source .venv/bin/activate
python scripts/render_report_html.py \
  --input "$S14_REPORT_OUTPUT_DIR/<原报告目录>/report.json" \
  --output "$S14_REPORT_OUTPUT_DIR/<原报告目录>/report.html"
```

报告包含：

- final_score
- risk_level
- M01-M08 module_scores
- metrics
- notes
- actions
- data_quality

## 测试

```bash
python -m unittest discover tests
python scripts/s14_feishu_entry.py --text 'S14诊断' --format text
```

## 后续计划

- 在服务器真实 OpenClaw 环境跑一次挂载验证。
- 根据 `report.json` 里的 `source_diagnostics` 修正字段映射。
