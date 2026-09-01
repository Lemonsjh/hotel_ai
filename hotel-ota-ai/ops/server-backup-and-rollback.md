# Server Backup And Rollback

Directory backup is mandatory before server updates:

```bash
cd /opt/openclaw/workspaces
BACKUP_DIR="hotel-ota-ai.backup.$(date +%F_%H%M%S)"
cp -a hotel-ota-ai "$BACKUP_DIR"
```

Rollback by preserving the failed directory and moving the selected backup back to `hotel-ota-ai`. Git tag/branch backups are supplemental and do not protect untracked files or `/etc/hotel-ota-ai/`.
