"""Stub notifier (STEP 5): logs pushes only. Telegram/web push come later with the same signature."""
import json
from logs_util import logger
log = logger("notifier")
SENT = []   # tests inspect this
async def push(text, buttons=None, kind="info", mint=None):
    """buttons: list of (label, url_or_callback). Returns True on success."""
    SENT.append({"text": text, "buttons": buttons or [], "kind": kind, "mint": mint})
    log.info(json.dumps({"kind": kind, "mint": mint, "text": text, "buttons": buttons or []}, ensure_ascii=False))
    return True
