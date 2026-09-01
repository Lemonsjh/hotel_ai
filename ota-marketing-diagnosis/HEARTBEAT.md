# Heartbeat

Before reporting success, verify:

```bash
python -c "import pymysql, openpyxl; print('deps ok')"
python scripts/s14_feishu_entry.py --text 'S14诊断' --format text
```

A valid S14 run must return a report URL under `S14_PUBLIC_BASE_URL` and must not point to demo filenames.
