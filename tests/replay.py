"""STEP 13 item 6: record the last 2h of real pumpfun migrations from chain, replay them through
Scanner -> Auditor -> Analyst -> Executor -> Risk in PAPER on a scratch db, print the Activity.
Usage: python -m tests.replay [record|replay|both]  (network; not part of the unit suite)."""
import asyncio, json, os, sys, tempfile, time
from datetime import datetime, timezone
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
import httpx
REC = os.path.join(ROOT, "logs", "raw", "replay_migrations.json")
RPC = "https://api.mainnet-beta.solana.com"
MIGRATOR = "9C4nRvhhVquCKATjDCx5FKvNS9PNgNqgyWy9AcoDjYv5"   # signer of MigrateV2 in the STEP 2 raw sample
WSOL = "So11111111111111111111111111111111111111112"

def record(hours=2):
    cl = httpx.Client(timeout=60); cut = time.time() - hours * 3600; sigs, before = [], None
    while True:
        p = {"limit": 1000, **({"before": before} if before else {})}
        r = cl.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": [MIGRATOR, p]}).json()["result"]
        if not r: break
        sigs += [s for s in r if (s.get("blockTime") or 0) >= cut and not s.get("err")]
        if (r[-1].get("blockTime") or 0) < cut: break
        before = r[-1]["signature"]
    out = []
    for s in sigs:
        for _ in range(5):
            j = cl.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                                   "params": [s["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]}).json()
            if "result" in j: break
            time.sleep(2)
        t = j.get("result")
        if not t: continue
        logs = " ".join(t["meta"].get("logMessages") or [])
        if "Migrate" not in logs: continue
        mints = {b["mint"] for b in (t["meta"].get("postTokenBalances") or []) if b["mint"] != WSOL}
        for m in mints: out.append({"signature": s["signature"], "mint": m, "txType": "migrate", "blockTime": s["blockTime"]})
        time.sleep(0.25)
    out.sort(key=lambda x: x["blockTime"])
    json.dump(out, open(REC, "w"), indent=1)
    print(f"recorded {len(out)} migrations from {len(sigs)} txs, {hours}h window")
    return out

async def replay():
    msgs = json.load(open(REC))
    os.environ["DESK_DB"] = os.path.join(tempfile.mkdtemp(), "replay.db")
    import db, bus, notifier, config
    from agents.scanner import Scanner
    from agents.auditor import Auditor
    from agents.analyst import Analyst
    from agents.executor import Executor
    from agents.risk import Risk
    notifier.BACKEND = None   # log only, nothing goes to Telegram
    c = db.connect(os.environ["DESK_DB"])
    sc, au, an, ex, rk = Scanner(c), Auditor(c), Analyst(c), Executor(c), Risk(c)
    for m in msgs:
        await sc.on_migration(m)
        iso = datetime.fromtimestamp(m["blockTime"], timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        c.execute("UPDATE coins SET migrated_at=? WHERE mint=?", (iso, m["mint"]))
        if m["mint"] in sc.room: sc.room[m["mint"]]["migratedAt"] = iso
    print(f"waiting room: {len(sc.room)} coins")
    for _ in range(2):                       # 2 Scanner ticks (the 2nd catches pairs DexScreener indexed late)
        await sc.tick()
        while not bus.auditor.empty(): await au.audit(bus.auditor.get_nowait())
        while not bus.analyst.empty(): j = bus.analyst.get_nowait(); await an.analyse(j["scan"], j["audit"])
        while not bus.executor.empty(): await ex.handle(bus.executor.get_nowait())
    for i in range(4):                       # 4 Risk polls, 15s apart, live prices
        await rk.tick(); await asyncio.sleep(15 if i < 3 else 0)
    q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]
    print("\nscans:", dict(q("select verdict,count(*) from scans group by verdict")), "| still waiting:", len(sc.room))
    print("kill reasons:", {r[0]: r[1] for r in q("select substr(reason,1,instr(reason||' ',' ')-1)||'…',count(*) from scans where verdict='kill' group by 1")})
    print("audits red by layer:", q("select layer,name,value_text from audits where pass=0"))
    print("verdicts:", q("select substr(mint,1,6),score,pass,reason from verdicts"))
    print("signals:", q("select substr(mint,1,6),size_usd,status,reason from signals"))
    print("positions:", q("select substr(mint,1,6),entry_price,status,exit_reason,pnl_usd from positions"))
    print("\nACTIVITY (newest first):")
    for r in q("select ts,kind,title,subtitle,value from activity order by ts desc"): print(" ", " | ".join(str(x) for x in r))
    if not q("select 1 from activity"): print("  (no activity rows)")
    print("\npushes (PAPER, logged only):"); [print("  ", p["text"].replace("\n", " / ")) for p in notifier.SENT]

if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "both"
    if a in ("record", "both"): record()
    if a in ("replay", "both"): asyncio.run(replay())
