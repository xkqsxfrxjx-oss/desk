"""Notifier: Telegram when the bot is running, else log only (tests). Same signature everywhere."""
import json
from logs_util import logger
log = logger("notifier")
SENT = []          # tests inspect this
BACKEND = None     # set by main.py to the Telegram instance
async def push(text, buttons=None, kind="info", mint=None):
    """buttons: list of (label, url_or_callback). Returns True on success."""
    SENT.append({"text": text, "buttons": buttons or [], "kind": kind, "mint": mint})
    log.info(json.dumps({"kind": kind, "mint": mint, "text": text, "buttons": buttons or []}, ensure_ascii=False))
    if BACKEND is None: return True
    return await BACKEND.send(text, buttons)
