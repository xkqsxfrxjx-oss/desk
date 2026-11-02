"""STEP 7 plan B: every 15s write encrypted JSON snapshots to publish/d/{DATA_PATH}/, push to Pages
(throttled), and the 60s price writer for tonight's other coins."""
import asyncio, json, os, shutil, time
from datetime import datetime, timedelta, timezone
import bus, config, db, links, publish, sources
from desk_crypto import encrypt, secrets_file
from agents.executor import stack, open_money
from logs_util import logger
log = logger("api")
WRITE_S = 15
PUBLISH_S = 360      # GitHub Pages soft limit is ~10 builds/hour
AGENTS = ["scanner", "auditor", "analyst", "executor", "risk"]

def since(c):
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds").replace("+00:00", "Z")
def rows(c, q, a=()): return [dict(r) for r in c.execute(q, a)]

def coin_name(c, mint):
    r = c.execute("SELECT name, symbol FROM coins WHERE mint=?", (mint,)).fetchone()
    return (r["name"] or r["symbol"]) if r and (r["name"] or r["symbol"]) else mint[:6]

def last_price(c, mint):
    r = c.execute("SELECT price FROM prices WHERE mint=? AND price IS NOT NULL ORDER BY ts DESC LIMIT 1", (mint,)).fetchone()
    return r[0] if r else None

def positions(c):
    out = []
    S = lambda k: config.get(c, "risk." + k)
    for p in rows(c, "SELECT * FROM positions WHERE status!='closed' ORDER BY opened_at"):
        px = last_price(c, p["mint"]) or p["entry_price"]
        trail = p["peak_price"] * (1 - S("trail_pct") / 100) if p["trail_active"] else None
        out.append({**p, "name": coin_name(c, p["mint"]), "price": px, "link": links.coin_url(p["mint"], "solana"),
                    "pnlUsd": round(p["size_usd"] * (px / p["entry_price"] - 1), 2), "pct": round(100 * (px / p["entry_price"] - 1), 2),
                    "exitLine": max(p["stop_price"], trail or 0), "trailLine": trail})
    return out

def agents_state(c, t0):
    hb = {r["agent"]: r["ts"] for r in rows(c, "SELECT * FROM heartbeats")}
    scans = rows(c, "SELECT * FROM scans WHERE ts>=? ORDER BY ts DESC", (t0,))
    audits = rows(c, "SELECT * FROM audits WHERE ts>=? ORDER BY id DESC", (t0,))
    audited = {}
    for a in reversed(audits): audited.setdefault(a["mint"], []).append(a)
    verdicts = rows(c, "SELECT * FROM verdicts WHERE ts>=? ORDER BY ts DESC", (t0,))
    sig = rows(c, "SELECT * FROM signals WHERE ts>=? ORDER BY ts DESC", (t0,))
    last_exit = c.execute("SELECT exit_reason FROM positions WHERE exit_reason IS NOT NULL ORDER BY closed_at DESC LIMIT 1").fetchone()
    rej = sum(1 for m, ls in audited.items() if any(l["pass"] == 0 for l in ls))
    last_audit = None
    if audits:
        m = audits[0]["mint"]
        last_audit = {"mint": m, "name": coin_name(c, m), "layers": audited.get(m, []),
                      "passed": len(audited.get(m, [])) == 8 and all(l["pass"] for l in audited[m]),
                      "reason": next((l["value_text"] for l in audited.get(m, []) if l["pass"] == 0), None)}
    feed = [{"mint": s["mint"], "name": coin_name(c, s["mint"]), "liq": s["liquidity_usd"], "verdict": s["verdict"],
             "reason": s["reason"], "ts": s["ts"], "link": links.coin_url(s["mint"], "solana")} for s in scans[:40]]
    return {
      "scanner": {"pools": c.execute("SELECT COUNT(*) FROM coins WHERE migrated_at>=?", (t0,)).fetchone()[0],
                  "passed": sum(1 for s in scans if s["verdict"] == "pass"), "killed": sum(1 for s in scans if s["verdict"] == "kill"), "feed": feed},
      "auditor": {"takenApart": len(audited), "rejected": rej, "last": last_audit},
      "analyst": {"scored": len(verdicts), "mode": config.get(c, "analyst.mode"), "minScore": config.get(c, "analyst.min_score"),
                  "last": ({**verdicts[0], "name": coin_name(c, verdicts[0]["mint"])} if verdicts else None)},
      "executor": {"trades": sum(1 for s in sig if s["status"] == "bought"), "stackPct": config.get(c, "executor.stack_pct"),
                   "last": ({**sig[0], "name": coin_name(c, sig[0]["mint"])} if sig else None)},
      "risk": {"open": c.execute("SELECT COUNT(*) FROM positions WHERE status!='closed'").fetchone()[0],
               "lastExit": {"trail": "Trailed out", "stop": "Stopped"}.get(last_exit[0], last_exit[0]) if last_exit else None,
               "stopPct": config.get(c, "risk.stop_pct"), "trailPct": config.get(c, "risk.trail_pct")},
      "heartbeats": hb, "paused": sorted(bus.PAUSED)}

def candles(c, mint, minutes=1):
    pts = rows(c, "SELECT ts, price, volume_m5 FROM prices WHERE mint=? AND price IS NOT NULL ORDER BY ts", (mint,))
    out = {}
    for p in pts:
        k = p["ts"][:16]
        o = out.get(k)
        if not o: out[k] = {"t": k + ":00Z", "o": p["price"], "h": p["price"], "l": p["price"], "c": p["price"], "v": p["volume_m5"]}
        else: o["h"] = max(o["h"], p["price"]); o["l"] = min(o["l"], p["price"]); o["c"] = p["price"]; o["v"] = p["volume_m5"]
    return list(out.values())[-300:]

def coin_doc(c, mint):
    coin = dict(c.execute("SELECT * FROM coins WHERE mint=?", (mint,)).fetchone())
    pos = rows(c, "SELECT * FROM positions WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,))
    p = pos[0] if pos else None
    exit_line = None
    if p and p["status"] != "closed":
        trail = p["peak_price"] * (1 - config.get(c, "risk.trail_pct") / 100) if p["trail_active"] else 0
        exit_line = max(p["stop_price"], trail)
    return {"coin": {**coin, "name": coin_name(c, mint)}, "link": links.coin_url(mint, "solana"), "candles": candles(c, mint),
            "scans": rows(c, "SELECT * FROM scans WHERE mint=? ORDER BY ts", (mint,)),
            "audit": rows(c, "SELECT * FROM audits WHERE mint=? ORDER BY layer", (mint,)),
            "verdict": (rows(c, "SELECT * FROM verdicts WHERE mint=?", (mint,)) or [None])[0],
            "signal": (rows(c, "SELECT * FROM signals WHERE mint=?", (mint,)) or [None])[0],
            "position": p, "exitLine": exit_line, "price": last_price(c, mint)}

def snapshot(c):
    t0 = since(c); mode = config.get(c, "desk.mode"); stk = stack(c, mode); om = open_money(c, mode)
    bal = rows(c, "SELECT ts, value FROM balance WHERE ts>=? ORDER BY ts", (t0,))
    start = config.get(c, "desk.paper_start_stack") if mode == "PAPER" else (bal[0]["value"] if bal else stk)
    pos = positions(c)
    upnl = sum(p["pnlUsd"] for p in pos)
    S = config.all_settings(c)
    state = {"updated": db.now(), "mode": mode, "stack": stk, "free": round(stk - om, 2), "equity": round(stk + upnl, 2),
             "pnlUsd": round(stk + upnl - start, 2), "pnlPct": round(100 * (stk + upnl - start) / start, 2) if start else 0,
             "positions": pos, "agents": agents_state(c, t0)}
    account = {"updated": state["updated"], "mode": mode, "plan": "B", "readOnly": True, "webPush": "Telegram only",
               "fomoHandle": S["desk.fomo_handle"], "profileUrl": links.profile_url(S["desk.fomo_handle"]),
               "signupUrl": links.SIGNUP_URL, "settings": {k: v for k, v in S.items() if k != "desk.rpc_url"},
               "rpc": "public" if "mainnet-beta" in S["desk.rpc_url"] else "custom", "minStack": config.min_stack(c),
               "changeLog": rows(c, "SELECT * FROM change_log ORDER BY ts DESC LIMIT 20")}
    acts = rows(c, "SELECT * FROM activity ORDER BY ts DESC LIMIT 200")
    for a in acts: a["link"] = links.coin_url(a["mint"], "solana") if a["mint"] else None
    mints = [r[0] for r in c.execute("""SELECT mint FROM coins WHERE migrated_at>=? AND mint IN
              (SELECT mint FROM scans UNION SELECT mint FROM audits UNION SELECT mint FROM positions)""", (t0,))]
    mints += [p["mint"] for p in pos if p["mint"] not in mints]
    return {"state.json": state, "chart.json": {"updated": state["updated"], "start": start, "points": bal},
            "activity.json": {"updated": state["updated"], "items": acts}, "account.json": account,
            "coins.json": {"updated": state["updated"], "mints": mints}, **{f"coin/{m}.json": coin_doc(c, m) for m in mints}}

def write(c):
    s = secrets_file(); dp, tok = s["DATA_PATH"], s["APP_TOKEN"]
    base = os.path.join(publish.STAGE, "d", dp); tmp = base + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(os.path.join(tmp, "coin"))
    for name, obj in snapshot(c).items():
        with open(os.path.join(tmp, name), "w") as f: json.dump(encrypt(obj, tok), f)
    shutil.rmtree(base, ignore_errors=True); os.replace(tmp, base)
    # keep only the current data path
    for d in os.listdir(os.path.join(publish.STAGE, "d")):
        if d != dp: shutil.rmtree(os.path.join(publish.STAGE, "d", d), ignore_errors=True)

class Api:
    def __init__(self, c, scanner=None): self.c = c; self.scanner = scanner; self.last_pub = 0
    async def writer(self):
        while True:
            try:
                write(self.c)
                if time.monotonic() - self.last_pub >= PUBLISH_S:
                    self.last_pub = time.monotonic()
                    await asyncio.to_thread(publish.publish); log.info("published")
            except Exception as e: log.info(f"write/publish error {type(e).__name__}: {e}")
            await asyncio.sleep(WRITE_S)
    async def prices(self):
        while True:
            try:
                room = list(self.scanner.room) if self.scanner else []
                ms = db.api_mints(self.c, since(self.c), room)
                if ms:
                    reads = await sources.dex_batch(ms)
                    db.write_prices(self.c, [(m, d["priceUsd"], d["volume_m5"]) for m, d in reads.items() if d and d.get("priceUsd")])
            except sources.RateLimited: await asyncio.sleep(30)
            except Exception as e: log.info(f"price writer error {e}")
            await asyncio.sleep(60)
    async def run(self):
        await asyncio.gather(self.writer(), self.prices())
