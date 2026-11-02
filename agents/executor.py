"""AGENT 4 · EXECUTOR. Arithmetic + 1 button. Never places orders."""
import asyncio
from datetime import datetime, timezone
import bus, config, db, links, notifier, sources
from logs_util import logger
log = logger("executor")

def stack(c, mode=None):
    mode = mode or config.get(c, "desk.mode")
    if mode == "LIVE": return float(config.get(c, "desk.live_stack"))
    pnl = c.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM positions WHERE mode='PAPER' AND status='closed'").fetchone()[0]
    return round(config.get(c, "desk.paper_start_stack") + pnl, 2)

def open_money(c, mode):
    return c.execute("SELECT COALESCE(SUM(size_usd),0) FROM positions WHERE mode=? AND status!='closed'", (mode,)).fetchone()[0]

def size_order(c, stk, free, pool_liq):
    """Returns (size|None, skip_reason|None, cap_hit, raw)."""
    E = lambda k: config.get(c, "executor." + k)
    raw = stk * E("stack_pct") / 100; size, cap = raw, "stack_pct"
    if pool_liq is not None and pool_liq * E("max_pool_pct") / 100 < size:
        size, cap = pool_liq * E("max_pool_pct") / 100, "max_pool_pct"
    mt = E("min_ticket_usd")
    if size < mt:
        if E("below_min") == "skip": return None, f"under ${mt:.2f}", cap, raw
        size, cap = mt, "bumped"
    if size > free: return None, "no free stack", cap, raw
    return round(size, 2), None, cap, raw

class Executor:
    def __init__(self, c): self.c = c
    async def handle(self, job, fresh=None):
        mint = job["scan"]["mint"]; name = job["scan"].get("name") or mint[:6]
        mode = config.get(self.c, "desk.mode")
        if self.c.execute("SELECT 1 FROM signals WHERE mint=?", (mint,)).fetchone(): return None   # 1 push per coin
        if self.c.execute("SELECT 1 FROM positions WHERE mint=? AND status!='closed'", (mint,)).fetchone(): return None
        link = links.coin_url(mint, "solana")
        stk = stack(self.c, mode); free = stk - open_money(self.c, mode)
        if fresh is None:
            try: fresh = (await sources.dex_batch([mint])).get(mint) or {}
            except Exception: fresh = {}
        price = fresh.get("priceUsd")
        def finish(status, reason, size=None, pct=None, cap=None, raw=None):
            out = {"agent": "executor", "mint": mint, "signalPrice": price, "sizeUsd": size, "stackPct": pct, "link": link,
                   "mode": mode, "status": status, "reason": reason}
            self.c.execute("INSERT OR IGNORE INTO signals(mint,ts,price,size_usd,stack_pct,link,mode,status,reason) VALUES(?,?,?,?,?,?,?,?,?)",
                           (mint, db.now(), price, size, pct, link, mode, status, reason))
            if status == "skipped": self.c.execute("INSERT OR IGNORE INTO skips VALUES(?,?)", (mint, "report"))
            log.info(f"{mint} stack={stk} raw={raw} cap={cap} size={size} mode={mode} status={status} reason={reason} link={link}")
            bus.emit("signal", out); return out
        if not price: return finish("skipped", "no price")
        size, why, cap, raw = size_order(self.c, stk, free, fresh.get("liquidity_usd"))
        if why: return finish("skipped", why, cap=cap, raw=raw)
        E = lambda k: config.get(self.c, "executor." + k)
        liq0 = job["scan"].get("liquidityUsd"); liq1 = fresh.get("liquidity_usd")
        if liq0 and liq1 is not None and liq1 < liq0 * (1 - E("recheck_liq_drop_pct") / 100): return finish("skipped", "liquidity dropping", cap=cap, raw=raw)
        p0 = job.get("price")
        if p0 and price > p0 * (1 + E("recheck_price_up_pct") / 100): return finish("skipped", "ran before the push", cap=cap, raw=raw)
        pct = round(100 * size / stk, 2) if stk else None
        stop_pct = config.get(self.c, "risk.stop_pct"); trail_pct = config.get(self.c, "risk.trail_pct")
        text = (f"{'PAPER · ' if mode == 'PAPER' else ''}Buy {name} · ${size:,.2f} · {pct:g}% of stack\n"
                f"Auditor 8/8 · Analyst {job['analyst']['score']} · stop -{stop_pct:g}% · trail {trail_pct:g}%")
        ok = False
        for _ in range(3):
            try:
                ok = await notifier.push(text, [("Buy on FOMO", link), ("Bought", f"bought:{mint}"), ("Skip", f"skip:{mint}")], "buy", mint)
            except Exception: ok = False
            if ok: break
        if not ok:
            log.info(f"{mint} push failed")
            if mode == "LIVE": return finish("skipped", "push failed", size, pct, cap, raw)
        out = finish("sent", None if ok else "push failed", size, pct, cap, raw)
        if mode == "PAPER": out = self.fill(mint, name, price, size, pct, link, mode)
        return out

    def fill(self, mint, name, price, size, pct, link, mode):
        stop_pct = config.get(self.c, "risk.stop_pct")
        now = db.now()
        with self.c:
            self.c.execute("BEGIN")
            self.c.execute("UPDATE signals SET status='bought' WHERE mint=?", (mint,))
            self.c.execute("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,stop_pct,mode) VALUES(?,?,?,?,?,?,?,?)",
                           (mint, now, price, size, price, price * (1 - stop_pct / 100), stop_pct, mode))
            hhmm = datetime.now().strftime("%H:%M")
            self.c.execute("INSERT INTO activity(ts,kind,mint,agent,title,subtitle,value) VALUES(?,?,?,?,?,?,?)",
                           (now, "bought", mint, "executor", f"Bought {name}", f"Executor · {hhmm}", f"${size:,.2f} · {pct:g}% of stack"))
        log.info(f"{mint} filled {mode} at {price} size={size}")
        bus.risk.put_nowait({"mint": mint})
        return {"agent": "executor", "mint": mint, "signalPrice": price, "sizeUsd": size, "stackPct": pct, "link": link,
                "mode": mode, "status": "bought", "reason": None}

    async def run(self):
        while True:
            while "executor" in bus.PAUSED: await asyncio.sleep(2)
            job = await bus.executor.get()
            try: await self.handle(job)
            except Exception as e: log.info(f"{job['scan'].get('mint')} executor crashed {type(e).__name__}: {e}")
