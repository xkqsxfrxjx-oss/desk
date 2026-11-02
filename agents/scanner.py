"""AGENT 1 · SCANNER. Counts and cuts graduated pumpfun coins on PumpSwap."""
import asyncio, json, re, unicodedata
from datetime import datetime, timezone
import websockets
import bus, config, db, fields, sources
from fields import get as fget
from logs_util import logger
log = logger("scanner")
WS = "wss://pumpportal.fun/api/data"

def _t(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def norm_name(s):
    s = "".join(ch for ch in (s or "").lower() if not unicodedata.category(ch).startswith(("S", "C")))
    return re.sub(r"[\s\d]+", "", s)
def is_copycat(name, symbol, runners):
    """runners: {normalized: display}. Exact match or one inside the other."""
    for cand in {norm_name(name), norm_name(symbol)} - {""}:
        for r, disp in runners.items():
            if r and (cand == r or cand in r or r in cand): return disp
    return None
def kill_reason(c, liq, top10, h1, copy_of):
    S = lambda k: config.get(c, "scanner." + k)
    if liq is None or liq < S("min_liquidity_usd"): return f"liq ${(liq or 0) / 1000:.1f}K"
    if top10 is not None and top10 > S("max_top10_pct"): return f"top 10 hold {top10:.0f}%"
    if h1 is not None and h1 > S("max_h1_change_pct"): return f"+{h1:.0f}% in 1h"
    if copy_of: return f"copycat of {copy_of}"
    return None

class Scanner:
    def __init__(self, c, rpc_url=None):
        self.c = c; self.room = {}      # mint -> {migratedAt, ...}
        self.sent = set(r[0] for r in c.execute("SELECT mint FROM scans WHERE verdict='pass' AND ts>=date('now')"))
        self.runners = {}; self.reconnects = 0; self.pools = 0
    def rpc(self): return config.get(self.c, "desk.rpc_url")

    async def on_migration(self, msg):
        mint = fget(msg, fields.MIGRATION["mint"])
        if not mint or mint in self.room or mint in self.sent: return
        if self.c.execute("SELECT 1 FROM coins WHERE mint=?", (mint,)).fetchone(): return
        self.pools += 1
        creator = fget(msg, fields.MIGRATION["creator"]) if fields.MIGRATION["creator"] else None
        if creator is None:
            try: creator = fget(await sources.rug_report(mint), fields.RUGCHECK_REPORT["creator"])
            except Exception as e: log.info(f"{mint} creator lookup failed: {e}")
        bal = None
        if creator:
            try: bal = str(sources.owner_balance(await sources.token_accounts(self.rpc(), mint), creator))
            except Exception as e: log.info(f"{mint} creator balance failed: {e}")
        now = db.now()
        self.c.execute("INSERT OR IGNORE INTO coins(mint,migrated_at,creator,creator_balance_at_migration) VALUES(?,?,?,?)",
                       (mint, now, creator, bal))
        self.room[mint] = {"migratedAt": now, "sig": fget(msg, fields.MIGRATION["signature"])}
        log.info(f"{mint} waiting creator={creator} bal={bal}")

    async def ws_loop(self):
        back = 1
        while True:
            try:
                async with websockets.connect(WS, ping_interval=20) as w:
                    await w.send(json.dumps({"method": "subscribeMigration"})); back = 1
                    while True:
                        raw = await asyncio.wait_for(w.recv(), config.get(self.c, "scanner.ws_silence_s"))
                        m = json.loads(raw)
                        if fget(m, fields.MIGRATION["mint"]): asyncio.create_task(self.on_migration(m))
            except Exception as e:
                self.reconnects += 1
                log.info(f"websocket reconnect #{self.reconnects} in {back}s ({type(e).__name__}: {e})")
                self.c.execute("INSERT OR REPLACE INTO heartbeats VALUES('scanner.ws_reconnect',?)", (db.now(),))
                await asyncio.sleep(back); back = min(back * 2, 60)

    def decide(self, mint, d, verdict, reason, top10, age):
        out = {"agent": "scanner", "mint": mint, "name": d.get("name"), "symbol": d.get("symbol"), "pool": d.get("pairAddress"),
               "liquidityUsd": d.get("liquidity_usd"), "top10Pct": top10, "h1ChangePct": d.get("priceChange_h1"),
               "ageMin": age, "verdict": verdict, "reason": reason, "ts": db.now()}
        self.c.execute("INSERT INTO scans(mint,ts,liquidity_usd,top10_pct,h1_change_pct,age_min,verdict,reason) VALUES(?,?,?,?,?,?,?,?)",
                       (mint, out["ts"], out["liquidityUsd"], top10, out["h1ChangePct"], age, "kill" if verdict == "drop" else verdict, reason))
        log.info(f"{mint} {verdict} {reason} liq={out['liquidityUsd']} top10={top10} h1={out['h1ChangePct']} age={age}")
        bus.emit("scan", out)
        self.room.pop(mint, None)
        return out

    async def tick(self):
        if not self.room: return
        try: reads = await sources.dex_batch(list(self.room))
        except sources.RateLimited:
            log.info(f"dexscreener 429, waiting 30s, room kept"); await asyncio.sleep(30); return
        except Exception as e:
            log.info(f"dexscreener error {e}"); return
        db.write_prices(self.c, [(m, d["priceUsd"], d["volume_m5"]) for m, d in reads.items() if d])
        for m, d in reads.items():
            if d and (d.get("priceChange_h24") or 0) >= config.get(self.c, "scanner.runner_h24_pct") and d.get("name"):
                self.runners[norm_name(d["name"])] = d["name"]
        now = datetime.now(timezone.utc)
        for mint, info in list(self.room.items()):
            age = int((now - _t(info["migratedAt"])).total_seconds() // 60)
            d = reads.get(mint)
            if d is None:      # DexScreener doesn't know the PumpSwap pair yet: wait
                if age >= config.get(self.c, "scanner.max_wait_min"): self.decide(mint, {}, "drop", "never qualified", None, age)
                continue
            self.c.execute("UPDATE coins SET name=?,symbol=?,pool=? WHERE mint=?", (d["name"], d["symbol"], d["pairAddress"], mint))
            top10 = None; reason = kill_reason(self.c, d["liquidity_usd"], None, None, None)
            if reason is None:
                try:
                    accs = await sources.token_accounts(self.rpc(), mint)
                    supply = int((await sources.mint_info(self.rpc(), mint))["supply"])
                    top10 = sources.top10_pct(accs, supply, mint, d["pairAddress"])
                except Exception as e:
                    log.info(f"{mint} top10 read failed ({e}), stays in room"); continue
                runners = {k: v for k, v in self.runners.items() if k != norm_name(d["name"])}
                reason = kill_reason(self.c, d["liquidity_usd"], top10, d["priceChange_h1"],
                                     is_copycat(d["name"], d["symbol"], runners))
            if reason: self.decide(mint, d, "kill", reason, top10, age); continue
            if age >= config.get(self.c, "scanner.min_pool_age_min") and mint not in self.sent:
                self.sent.add(mint)
                await bus.auditor.put(self.decide(mint, d, "pass", None, top10, age)); continue
            if age >= config.get(self.c, "scanner.max_wait_min"): self.decide(mint, d, "drop", "never qualified", top10, age)

    async def run(self):
        asyncio.create_task(self.ws_loop())
        while True:
            try:
                if "scanner" not in bus.PAUSED: await self.tick()
            except Exception as e: log.info(f"tick error {type(e).__name__}: {e}")
            await asyncio.sleep(config.get(self.c, "scanner.poll_s"))
