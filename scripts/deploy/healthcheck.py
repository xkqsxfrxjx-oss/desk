"""Replaces the box 'desk-health' routine. Runs as root via desk-health.timer.
If any agent heartbeat is older than STALE_S (or none exist), restart the service and alert on Telegram
through the existing notifier/Telegram backend. Silent when healthy. Never prints secrets."""
import asyncio, os, subprocess, sys, time
from datetime import datetime
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import db, notifier
from telegram import Telegram
STALE_S = int(os.environ.get("DESK_STALE_S", "300"))
AGENTS = ["scanner", "auditor", "analyst", "executor", "risk", "api", "telegram"]

def stale(c):
    now = time.time(); out = {}
    rows = dict(c.execute("SELECT agent, ts FROM heartbeats").fetchall())
    for a in AGENTS:
        ts = rows.get(a)
        age = now - datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else None
        if age is None or age > STALE_S: out[a] = None if age is None else int(age)
    return out

def main():
    c = db.connect(); bad = stale(c)
    if not bad: print("healthy"); return 0
    cmd = os.environ.get("DESK_RESTART_CMD") or "systemctl restart " + os.environ.get("DESK_SERVICE", "desk.service")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    detail = ", ".join(f"{a} {'none' if s is None else f'{s//60} min'}" for a, s in bad.items())
    msg = f"⚠️ Desk (VPS) heartbeat stale: {detail}. Restarted ({'ok' if r.returncode == 0 else 'FAILED'}). PAPER mode."
    print(msg)
    try:
        tg = Telegram(c)
        if tg.token: notifier.BACKEND = tg
        asyncio.run(notifier.push(msg, kind="alert"))
    except Exception as e: print("telegram alert failed:", type(e).__name__)
    return 0 if r.returncode == 0 else 1

if __name__ == "__main__": sys.exit(main())
