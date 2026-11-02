"""AGENT 5 · RISK. Exits by rule, sends the Sell button. Never places orders."""
import asyncio
from datetime import datetime, timezone
import bus, config, db, fees, links, notifier, sources
from logs_util import logger
log = logger("risk")

class Risk:
    def __init__(self, c): self.c = c; self.no_price = {}; self.last_exit = None
    S = lambda self, k: config.get(self.c, "risk." + k)

    def tighten(self, p):
        """New stop setting applies to open positions only if tighter. Never moves a stop down."""
        s = self.S("stop_pct")
        if s < p["stop_pct"]:
            new = p["entry_price"] * (1 - s / 100)
            if new > p["stop_price"]:
                self.c.execute("UPDATE positions SET stop_price=?, stop_pct=? WHERE id=?", (new, s, p["id"]))
                p["stop_price"], p["stop_pct"] = new, s
        return p

    async def evaluate(self, p, price, liq, now=None):
        """One poll for one position. Returns exit dict or None."""
        now = now or datetime.now(timezone.utc)
        p = self.tighten(dict(p))
        name = p.get("name") or p["mint"][:6]
        if liq is not None and liq <= 0:
            last = self.c.execute("SELECT price FROM prices WHERE mint=? AND price IS NOT NULL ORDER BY ts DESC LIMIT 1", (p["mint"],)).fetchone()
            return await self.exit(p, "pulled", price or (last[0] if last else p["peak_price"]), name)
        peak = max(p["peak_price"], price)
        if peak != p["peak_price"]: self.c.execute("UPDATE positions SET peak_price=? WHERE id=?", (peak, p["id"])); p["peak_price"] = peak
        e = p["entry_price"]; action = None
        if price <= p["stop_price"]: action = "stop"
        else:
            if not p["trail_active"] and price >= e * (1 + self.S("trail_start_pct") / 100):
                self.c.execute("UPDATE positions SET trail_active=1 WHERE id=?", (p["id"],)); p["trail_active"] = 1
            if p["trail_active"] and price <= peak * (1 - self.S("trail_pct") / 100): action = "trail"
            elif (now - datetime.fromisoformat(p["opened_at"].replace("Z", "+00:00"))).total_seconds() >= self.S("timeout_h") * 3600 \
                    and price < e * (1 + self.S("timeout_min_gain_pct") / 100): action = "timeout"
        trail_line = peak * (1 - self.S("trail_pct") / 100) if p["trail_active"] else None
        log.info(f"{p['mint']} price={price} peak={peak} stop={p['stop_price']} trail={trail_line} action={action or 'hold'}")
        return await self.exit(p, action, price, name) if action else None

    async def exit(self, p, reason, price, name):
        mode = p["mode"]; link = links.coin_url(p["mint"], "solana"); disc = config.get(self.c, "desk.fees_ref_discount")
        value = p["size_usd"] * price / p["entry_price"]
        fee = fees.round_trip(p["size_usd"], value, disc)
        pnl = round(value - p["size_usd"] - fee, 2); pct = round(100 * pnl / p["size_usd"], 2)
        status = "closed" if mode == "PAPER" else "exiting"; now = db.now()
        with self.c:
            self.c.execute("BEGIN")
            self.c.execute("UPDATE positions SET status=?, exit_price=?, exit_reason=?, pnl_usd=?, fees_usd=?, closed_at=? WHERE id=?",
                           (status, price, reason, pnl, round(fee, 2), now if status == "closed" else None, p["id"]))
            if reason == "stop":
                kind, title, sub, val = "stopped", f"Stopped {name}", f"Risk · -{p['stop_pct']:g}% stop", f"-${abs(pnl):,.2f}"
            else:
                label = {"trail": "trailing stop", "timeout": "timeout", "pulled": "liquidity pulled"}[reason]
                kind, title, sub, val = "sold", f"Sold {name}", f"Risk · {label}", f"{'+' if pnl >= 0 else '-'}${abs(pnl):,.2f} / {pct:+g}%"
            self.c.execute("INSERT INTO activity(ts,kind,mint,agent,title,subtitle,value) VALUES(?,?,?,?,?,?,?)",
                           (now, kind, p["mint"], "risk", title, sub, val))
        sign = lambda x: f"{'+' if x >= 0 else '-'}${abs(x):,.2f}"
        txt = {"trail": f"Sold {name} · {sign(pnl)} ({pct:+g}%)",
               "stop": f"{name} hit the -{p['stop_pct']:g}% stop · -${abs(pnl):,.2f}",
               "timeout": f"Sell {name}, dead money · {pct:+g}% in {self.S('timeout_h'):g}h",
               "pulled": f"Sell {name} now, liquidity pulled · {sign(pnl)}"}[reason]
        if mode == "PAPER": txt = "PAPER · " + txt
        await notifier.push(txt, [("Sell on FOMO", link), ("Sold", f"sold:{p['mint']}")], "sell", p["mint"])
        self.last_exit = "Trailed out" if reason == "trail" else "Stopped" if reason == "stop" else reason
        out = {"agent": "risk", "mint": p["mint"], "name": name, "ts": now, "reason": reason, "entryPrice": p["entry_price"],
               "exitPrice": price, "peakPrice": p["peak_price"], "pnlUsd": pnl, "pct": pct, "feesUsd": round(fee, 2),
               "stopPct": p["stop_pct"], "mode": mode, "status": status, "link": link}
        log.info(f"{p['mint']} EXIT {out}"); bus.emit("exit", out)
        return out

    async def tick(self):
        rows = [dict(r) for r in self.c.execute(
            "SELECT p.*, c.name FROM positions p JOIN coins c USING(mint) WHERE p.status='open'")]
        if not rows: return
        try: reads = await sources.dex_batch([r["mint"] for r in rows])
        except sources.RateLimited:
            log.info(f"429, backing off {self.S('backoff_429_s')}s, missed poll for {len(rows)} positions")
            await asyncio.sleep(self.S("backoff_429_s")); return
        except Exception as e:
            reads = {r["mint"]: None for r in rows}; log.info(f"dexscreener error {e}")
        db.write_prices(self.c, [(m, d["priceUsd"], d["volume_m5"]) for m, d in reads.items() if d and d.get("priceUsd")])
        for p in rows:
            d = reads.get(p["mint"]) or {}
            price = d.get("priceUsd")
            if not price:
                n = self.no_price[p["mint"]] = self.no_price.get(p["mint"], 0) + 1
                log.info(f"{p['mint']} no price ({n})")
                if n == self.S("no_price_polls"):
                    await notifier.push(f"{p['name'] or p['mint'][:6]}: no price for 1 min",
                                        [("Sell on FOMO", links.coin_url(p["mint"], "solana"))], "alert", p["mint"])
                continue
            self.no_price[p["mint"]] = 0
            await self.evaluate(p, price, d.get("liquidity_usd"))

    async def run(self):
        while True:
            try: await self.tick()
            except Exception as e: log.info(f"tick error {type(e).__name__}: {e}")
            await asyncio.sleep(self.S("poll_s"))
