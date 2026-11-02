# Desk → always-on VPS (Ubuntu 24.04)

Box side (no secret is ever printed):
1. `bash scripts/deploy/make-bundle.sh` → `.secrets/desk-bundle.enc` + `.secrets/desk-bundle.pass` (gitignored, 600).
2. Stop the box desk (avoid double Telegram polling / Pages publish): `pkill -f "python main.py"`, pause the `desk-health` routine.
3. `bash scripts/deploy/push-to-vps.sh root@SERVER_IP` — scp over SSH (key `~/.ssh/desk_vps`), runs `install.sh`, shreds the bundle on the server.

Server side, `install.sh` does: apt deps → user `desk` → clone to `/opt/desk` → venv + requirements
(playwright/pytest skipped) → decrypt bundle into `/etc/desk/desk.env` (root 600, systemd EnvironmentFile),
`/opt/desk/.secrets/env`, `owner.json`, `data/desk.db` → `desk.service` (Restart=always) + `desk-health.timer`
(every 2 min; heartbeat >5 min stale → restart + Telegram alert via notifier).

Check: `systemctl status desk`, `journalctl -u desk-health`, `tail /opt/desk/logs/main.log`.
