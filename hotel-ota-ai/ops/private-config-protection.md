# Private Config Protection

Never commit or overwrite:

- `/etc/hotel-ota-ai/feishu-role-map.json`
- `/etc/hotel-ota-ai/database-source.json`
- `/etc/hotel-ota-ai/*.json`
- `.env`
- `config/*.local.*`
- `config/*secret*`
- any file containing API keys, DSNs, tokens, passwords, role maps, or real Open IDs

GitHub should only contain `.example`, `.template`, or `.sample` files for configuration.
