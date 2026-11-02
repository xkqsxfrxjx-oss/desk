"""AGENT 2 · AUDITOR. 8 layers in order, first red kills."""
import asyncio, json, time
from datetime import datetime, timezone
import bus, config, db, fields, sources
from fields import get as fget
from logs_util import logger
import notifier
log = logger("auditor")
NAMES = ["Mint authority", "Freeze authority", "Dev wallet", "Top 10 holders", "Liquidity", "Pool age",
         "Bundled wallets", "Delegations"]
NODATA = {1: "mint", 2: "freeze", 3: "dev", 4: "top 10", 5: "liquidity", 6: "pool age", 7: "bundles", 8: "delegations"}
SOURCE = {1: "rpc", 2: "rpc", 3: "rpc", 4: "rpc", 5: "rugcheck", 6: "rpc", 7: "rugcheck", 8: "rpc"}

class NoData(Exception): pass

def biggest_group(graph):
    """Layer 7: holders joined by links (connected components); size of the biggest. Raises NoData."""
    if not isinstance(graph, list): raise NoData()
    parent = {}
    def f(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for net in graph:
        if fields.RUGCHECK_GRAPH["edges"][1] not in net or "nodes" not in net: raise NoData()
        holders = {n["id"] for n in net["nodes"] if (n.get("holdings") or 0) > 0}
        for h in holders: parent.setdefault(h, h)
        for e in net["links"]:
            a, b = e.get("source"), e.get("target")
            if a in holders and b in holders: parent[f(a)] = f(b)
    sizes = {}
    for h in parent: sizes[f(h)] = sizes.get(f(h), 0) + 1
    big = max(sizes.values(), default=0)
    return big if big > 1 else 0

class Auditor:
    def __init__(self, c):
        self.c = c; self.done = set(); self.layer8_down = False; self.layer8_kills = 0
    S = lambda self, k: config.get(self.c, "auditor." + k)

    async def _retry(self, fn):
        last = None
        for i in range(self.S("retries")):
            try: return await asyncio.wait_for(fn(), 60)
            except Exception as e:
                last = e
                if i < self.S("retries") - 1: await asyncio.sleep(self.S("retry_wait_s"))
        raise NoData(str(last))

    async def audit_adhoc(self, mint):
        """'buy X' on a coin the desk never pushed: audit only, no bus, no activity."""
        try: d = (await sources.dex_batch([mint])).get(mint) or {}
        except Exception: d = {}
        return await self.audit({"mint": mint, "name": d.get("name"), "pool": d.get("pairAddress"), "liquidityUsd": d.get("liquidity_usd")}, forward=False)

    async def audit(self, scan, forward=True):
        mint = scan["mint"]; url = config.get(self.c, "desk.rpc_url"); ts = db.now()
        if forward and mint in self.done: return None
        if forward: self.done.add(mint)
        coin = dict(self.c.execute("SELECT * FROM coins WHERE mint=?", (mint,)).fetchone())
        pool = scan.get("pool") or coin.get("pool")
        cache = {}
        async def get(k, fn):
            if k not in cache: cache[k] = await self._retry(fn)
            return cache[k]
        mi = lambda: get("mint", lambda: sources.mint_info(url, mint))
        accs = lambda: get("accs", lambda: sources.token_accounts(url, mint))
        layers, reason, holders = [], None, None
        for n in range(1, 9):
            t0 = time.monotonic(); raw = None
            try:
                if n == 1:
                    raw = (await mi())["mintAuthority"]; ok, val = raw is None, ("Revoked" if raw is None else "mint not revoked")
                elif n == 2:
                    raw = (await mi())["freezeAuthority"]; ok, val = raw is None, ("Revoked" if raw is None else "freeze not revoked")
                elif n == 3:
                    try: supply = int((await mi())["supply"] or 0)
                    except NoData: supply = 0
                    if not supply: ok, val = False, "no supply"
                    elif not coin.get("creator") or coin.get("creator_balance_at_migration") is None: raise NoData("creator")
                    else:
                        bal = sources.owner_balance(await accs(), coin["creator"]); start = int(coin["creator_balance_at_migration"])
                        pct = 100 * bal / supply; raw = {"bal": bal, "start": start, "pct": pct}
                        if bal < start: ok, val = False, "dev sold"
                        elif pct >= self.S("max_dev_pct"): ok, val = False, f"dev holds {pct:.0f}%"
                        else: ok, val = True, f"{pct:.1f}% · sold 0"
                elif n == 4:
                    raw = sources.top10_pct(await accs(), int((await mi())["supply"]), mint, pool)
                    if raw is None: raise NoData()
                    ok, val = raw < self.S("max_top10_pct"), (f"{raw:.1f}%" if raw < self.S("max_top10_pct") else f"top 10 hold {raw:.0f}%")
                elif n == 5:
                    rep = await get("report", lambda: sources.rug_report(mint))
                    mk = next((m for m in (fget(rep, fields.RUGCHECK_REPORT["markets"]) or [])
                               if fget(m, fields.RUGCHECK_REPORT["market_pool"]) == pool), None)
                    locked = fget(mk, fields.RUGCHECK_REPORT["lp_locked_pct"]) if mk else None
                    if locked is None: raise NoData()
                    fresh = (await get("dex", lambda: sources.dex_batch([mint]))).get(mint) or {}
                    liq0, liq1 = scan.get("liquidityUsd"), fresh.get("liquidity_usd")
                    raw = {"lpLockedPct": locked, "liq_scan": liq0, "liq_now": liq1}
                    if locked < self.S("min_lp_locked_pct"): ok, val = False, "liquidity unlocked"
                    elif liq0 and (liq1 is None or liq1 < liq0 * (1 - self.S("max_liq_drop_pct") / 100)): ok, val = False, "liquidity pulled"
                    else: ok, val = True, f"{locked:g}% locked"
                elif n == 6:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(coin["migrated_at"].replace("Z", "+00:00"))).total_seconds() / 60
                    raw = age; ok = age >= self.S("min_pool_age_min")
                    val = (f"{int(age // 60)}h{int(age % 60)}m" if age >= 60 else f"{int(age)}m") if ok else "pool too young"
                elif n == 7:
                    raw = biggest_group(await get("graph", lambda: sources.rug_graph(mint)))
                    ok = raw < self.S("max_bundled"); val = ("None" if raw == 0 else f"{raw} bundled wallets") if ok else f"{raw} bundled wallets"
                elif n == 8:
                    try: a = await accs()
                    except NoData:
                        if not self.layer8_down:
                            self.layer8_down = True
                            await notifier.push("layer 8 down, every coin is red until rpc_url changes", kind="alert")
                        self.layer8_kills += 1; raise
                    self.layer8_down = False
                    holders = sum(1 for x in a if x["amount"] > 0)
                    self.c.execute("UPDATE coins SET holders=? WHERE mint=?", (holders, mint))
                    by = {}
                    for x in a:
                        if x["delegate"]: by[x["delegate"]] = by.get(x["delegate"], 0) + 1
                    d, cnt = max(by.items(), key=lambda kv: kv[1], default=(None, 0)); raw = {"top_delegate_accounts": cnt}
                    ok = cnt <= self.S("max_delegated_accounts")
                    val = "None" if cnt == 0 else (f"{cnt} delegated" if ok else f"{cnt} wallets → {d[:4]}...{d[-3:]}")
            except NoData as e:
                ok, val, raw = False, f"no data: {NODATA[n]}", str(e)
            ms = int(1000 * (time.monotonic() - t0))
            L = {"n": n, "name": NAMES[n - 1], "pass": ok, "value": val, "source": SOURCE[n]}
            layers.append(L)
            self.c.execute("INSERT OR REPLACE INTO audits(mint,ts,layer,name,value_text,pass,source) VALUES(?,?,?,?,?,?,?)",
                           (mint, db.now(), n, L["name"], val, int(ok), L["source"]))
            log.info(f"{mint} layer {n} {L['name']} raw={json.dumps(raw, default=str)[:300]} -> {'ok' if ok else 'RED'} {val} {ms}ms")
            bus.emit("audit_layer", {"mint": mint, **L})
            if not ok: reason = val; break
        for n in range(len(layers) + 1, 9):
            layers.append({"n": n, "name": NAMES[n - 1], "pass": None, "value": "not checked", "source": SOURCE[n]})
        out = {"agent": "auditor", "mint": mint, "ts": ts, "passed": reason is None, "layersChecked": len([l for l in layers if l["pass"] is not None]),
               "layers": layers, "holders": holders, "reason": reason}
        log.info(f"{mint} verdict {'PASS 8/8' if reason is None else 'RED ' + reason}")
        if not forward: return out
        if reason is None:
            await bus.analyst.put({"scan": scan, "audit": out})
        else:
            name = scan.get("name") or mint[:6]
            self.c.execute("INSERT INTO activity(ts,kind,mint,agent,title,subtitle,value) VALUES(?,?,?,?,?,?,?)",
                           (db.now(), "rejected", mint, "auditor", f"Rejected {name}", f"Auditor · {reason}", "Skipped"))
            self.c.execute("INSERT OR IGNORE INTO skips VALUES(?,?)", (mint, "report"))
        return out

    async def run(self):
        while True:
            while "auditor" in bus.PAUSED: await asyncio.sleep(2)
            scan = await bus.auditor.get()
            if not config.get(self.c, "auditor.enabled"): continue
            try: await self.audit(scan)
            except Exception as e: log.info(f"{scan.get('mint')} audit crashed {type(e).__name__}: {e}")
