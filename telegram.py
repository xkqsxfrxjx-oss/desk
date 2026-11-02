"""STEP 9: Telegram long polling, owner lock, pushes with FOMO buttons, callbacks and commands.
TG_TOKEN comes from the environment and is never logged."""
import asyncio, json, os, re
import httpx
import bus, config, db, links, notifier
from agents.executor import stack, open_money
from logs_util import logger
log = logger("telegram")
ROOT = os.path.dirname(os.path.abspath(__file__))
PAGES = "https://xkqsxfrxjx-oss.github.io/desk/"
AGENTS = ["scanner", "auditor", "analyst", "executor", "risk"]
HELP = ("Commands:\n buy X · sell X · why X\n pause Scanner · resume Scanner\n set stop to -8%\n stack 1240\n"
        " status\n paper | live\n invite\n report\n compare\nX = name, symbol or mint.")

class Telegram:
    def __init__(self, c, token=None):
        self.c = c; self.token = token or os.environ.get("TG_TOKEN", "")
        self.base = f"https://api.telegram.org/bot{self.token}/"
        self.owner = json.load(open(os.path.join(ROOT, "owner.json")))["owner_chat_id"]
        self.http = httpx.AsyncClient(timeout=40); self.offset = None; self.live_pending = False
        self.auditor = None   # set by main for "buy X" on an unseen coin

    async def call(self, method, **kw):
        try:
            r = await self.http.post(self.base + method, json=kw)
            j = r.json()
            if not j.get("ok"): log.info(f"{method} failed: {j.get('description')}")
            return j
        except Exception as e:
            log.info(f"{method} error {type(e).__name__}")   # never log the URL (it holds the token)
            return {"ok": False}

    def kb(self, buttons):
        if not buttons: return None
        row = []
        for label, target in buttons:
            row.append({"text": label, "url": target} if target.startswith("http") else {"text": label, "callback_data": target[:64]})
        return {"inline_keyboard": [row]}

    async def send(self, text, buttons=None):
        kw = {"chat_id": self.owner, "text": text, "disable_web_page_preview": True}
        if buttons: kw["reply_markup"] = self.kb(buttons)
        return bool((await self.call("sendMessage", **kw)).get("ok"))

    # ---------- lookups ----------
    def find(self, x):
        x = x.strip()
        rows = [dict(r) for r in self.c.execute(
            "SELECT mint,name,symbol FROM coins WHERE mint=? OR lower(name)=lower(?) OR lower(symbol)=lower(?) OR lower(symbol)=lower(?)",
            (x, x, x, x.lstrip("$")))]
        return rows

    async def resolve(self, x):
        rows = self.find(x)
        if len(rows) == 1: return rows[0]
        if not rows:
            if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", x.strip()): return {"mint": x.strip(), "name": None, "symbol": None}
            await self.send(f"I don't know {x}. Send me its mint address."); return None
        await self.send("Which one?\n" + "\n".join(f"{r['name'] or r['symbol']} · {links.coin_url(r['mint'], 'solana')}" for r in rows))
        return None

    def nm(self, r): return r.get("name") or r.get("symbol") or r["mint"][:6]

    # ---------- commands ----------
    async def handle_text(self, text):
        t = text.strip(); low = t.lower().lstrip("/")
        if low in ("start",): return await self.send("Desk online. " + HELP)
        if self.live_pending:
            self.live_pending = False
            if t == "LIVE":
                try: return await self.send(config.set(self.c, "mode", "LIVE", who="owner-typed-LIVE"))
                except config.SettingError as e: return await self.send(str(e))
            return await self.send("Staying in PAPER.")
        m = re.match(r"(buy|sell|why)\s+(.+)", low)
        if m:
            r = await self.resolve(t.split(None, 1)[1])
            if r: await getattr(self, "cmd_" + m.group(1))(r)
            return
        m = re.match(r"(pause|resume)\s+(\w+)", low)
        if m: return await self.cmd_pause(m.group(1), m.group(2))
        m = re.match(r"set\s+(.+?)\s+to\s+(.+)", t, re.I) or re.match(r"set\s+(\S+)\s+(.+)", t, re.I)
        if m:
            try: return await self.send(config.set(self.c, m.group(1), m.group(2)) + self.ticket_note())
            except config.SettingError as e: return await self.send(str(e))
        m = re.match(r"stack\s+\$?([\d,.]+)", low)
        if m:
            try: return await self.send(config.set(self.c, "desk.live_stack", m.group(1)) + self.ticket_note(float(m.group(1).replace(",", ""))))
            except config.SettingError as e: return await self.send(str(e))
        if low == "status": return await self.cmd_status()
        if low == "paper":
            return await self.send(config.set(self.c, "mode", "PAPER"))
        if low == "live": return await self.cmd_live()
        if low == "compare":
            import shadow
            since = self.c.execute("SELECT MIN(ts) FROM change_log WHERE who='matias'").fetchone()[0] or "1970-01-01T00:00:00Z"
            return await self.send(shadow.compare_text(self.c, since))
        if low == "invite": return await self.send(f"New to FOMO? {links.SIGNUP_URL}")
        if low == "report":
            import report
            u = report.last_link(self.c)
            return await self.send(f"Last morning Page: {u}" if u else "No morning Page yet. The first one comes after the first night.")
        await self.send(HELP)

    def ticket_note(self, stk=None):
        ok, msg = config.ticket_check(self.c, stk if stk is not None else stack(self.c))
        return f"\n{msg}" if msg else ""

    async def cmd_buy(self, r):
        mint = r["mint"]; link = links.coin_url(mint, "solana")
        sig = self.c.execute("SELECT * FROM signals WHERE mint=?", (mint,)).fetchone()
        if sig and sig["status"] in ("sent", "bought"):
            return await self.send(f"Buy {self.nm(r)} · ${sig['size_usd']:,.2f} · {sig['stack_pct']:g}% of stack",
                                   [("Buy on FOMO", link), ("Bought", f"bought:{mint}"), ("Skip", f"skip:{mint}")])
        if self.auditor is None: return await self.send(f"{self.nm(r)}: Auditor is not running.", [("Buy on FOMO", link)])
        self.c.execute("INSERT OR IGNORE INTO coins(mint,migrated_at) VALUES(?,?)", (mint, db.now()))
        out = await self.auditor.audit_adhoc(mint)
        lines = [f"{l['n']} {l['name']}: {l['value']}" for l in out["layers"]]
        await self.send(f"{self.nm(r)} · Auditor {'8/8' if out['passed'] else 'RED'}\n" + "\n".join(lines) +
                        "\nnot sized, not on the desk", [("Buy on FOMO", link)])

    async def cmd_sell(self, r):
        p = self.c.execute("SELECT * FROM positions WHERE mint=? AND status!='closed'", (r["mint"],)).fetchone()
        if not p: return await self.send(f"No open position in {self.nm(r)}. {links.coin_url(r['mint'], 'solana')}")
        await self.send(f"Sell {self.nm(r)} · entry ${p['entry_price']:.8g} · ${p['size_usd']:,.2f}",
                        [("Sell on FOMO", links.coin_url(r["mint"], "solana")), ("Sold", f"sold:{r['mint']}")])

    async def cmd_why(self, r):
        mint = r["mint"]; link = links.coin_url(mint, "solana"); nm = self.nm(r)
        s = self.c.execute("SELECT * FROM scans WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,)).fetchone()
        a = self.c.execute("SELECT * FROM audits WHERE mint=? AND pass=0 ORDER BY layer LIMIT 1", (mint,)).fetchone()
        v = self.c.execute("SELECT * FROM verdicts WHERE mint=?", (mint,)).fetchone()
        g = self.c.execute("SELECT * FROM signals WHERE mint=?", (mint,)).fetchone()
        p = self.c.execute("SELECT * FROM positions WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,)).fetchone()
        if p and p["exit_reason"]: msg = f"Risk exited {nm}: {p['exit_reason']} at ${p['exit_price']:.8g}, {p['closed_at'] or 'exiting'}"
        elif p: msg = f"{nm} is open, stop -{p['stop_pct']:g}%"
        elif g and g["status"] == "skipped": msg = f"Executor skipped {nm}: {g['reason']} at {g['ts']}"
        elif v and not v["pass"]: msg = f"Analyst rejected {nm}: {v['reason']} at {v['ts']}"
        elif a: msg = f"Auditor stopped {nm} at layer {a['layer']} {a['name']}: {a['value_text']} at {a['ts']}"
        elif s and s["verdict"] == "kill": msg = f"Scanner killed {nm}: {s['reason']} at {s['ts']}"
        elif s: msg = f"{nm} passed Scanner at {s['ts']} and is still in the pipeline"
        else: msg = f"{nm} hasn't been judged yet (still in the waiting room or never seen)"
        await self.send(msg + f"\n{link}")

    async def cmd_pause(self, act, who):
        who = who.lower()
        if who not in AGENTS: return await self.send(f"Agents: {', '.join(AGENTS)}")
        if act == "pause":
            if who == "risk" and self.c.execute("SELECT 1 FROM positions WHERE status!='closed'").fetchone():
                return await self.send("Risk can't be paused while a position is open.")
            bus.PAUSED.add(who); return await self.send(f"{who.capitalize()} paused")
        bus.PAUSED.discard(who); await self.send(f"{who.capitalize()} resumed")

    async def cmd_status(self):
        mode = config.get(self.c, "desk.mode"); stk = stack(self.c, mode); free = stk - open_money(self.c, mode)
        ps = [dict(r) for r in self.c.execute("SELECT p.*, c.name FROM positions p JOIN coins c USING(mint) WHERE p.status!='closed'")]
        head = f"{mode} · balance ${stk:,.2f} · free ${free:,.2f} · {len(ps)} open"
        if bus.PAUSED: head += f"\npaused: {', '.join(sorted(bus.PAUSED))}"
        await self.send(head)
        for p in ps:
            await self.send(f"{p['name'] or p['mint'][:6]} · ${p['size_usd']:,.2f} · entry ${p['entry_price']:.8g} · stop -{p['stop_pct']:g}%",
                            [("Sell on FOMO", links.coin_url(p["mint"], "solana"))])

    async def cmd_live(self):
        first = self.c.execute("SELECT MIN(ts) FROM balance").fetchone()[0]
        from datetime import datetime, timezone
        hours = (datetime.now(timezone.utc) - datetime.fromisoformat(first.replace("Z", "+00:00"))).total_seconds() / 3600 if first else 0
        if hours < 12: return await self.send("LIVE needs at least 1 full PAPER night first.")
        self.live_pending = True; await self.send("Type LIVE to switch. Money only moves when you tap Buy on FOMO.")

    # ---------- callbacks ----------
    async def handle_cb(self, cb):
        data = cb.get("data", ""); kind, _, mint = data.partition(":")
        await self.call("answerCallbackQuery", callback_query_id=cb["id"])
        name = (self.find(mint) or [{"mint": mint}])[0]; nm = self.nm(name)
        if kind == "skip":
            self.c.execute("INSERT OR IGNORE INTO skips VALUES(?,?)", (mint, "report"))
            self.c.execute("UPDATE signals SET status='skipped', reason='skipped by you' WHERE mint=? AND status='sent'", (mint,))
            return await self.send(f"Skipped {nm} for the night")
        if kind == "bought":
            sig = self.c.execute("SELECT * FROM signals WHERE mint=?", (mint,)).fetchone()
            if not sig: return await self.send("No signal for that coin.")
            if sig["mode"] == "PAPER": return await self.send(f"PAPER fills on its own. {nm} is already open.")
            if sig["status"] != "sent": return await self.send(f"{nm}: signal is {sig['status']}.")
            from agents.executor import Executor
            Executor(self.c).fill(mint, nm, sig["price"], sig["size_usd"], sig["stack_pct"], sig["link"], "LIVE")
            return await self.send(f"Bought {nm} logged, Risk is guarding it")
        if kind == "sold":
            p = self.c.execute("SELECT * FROM positions WHERE mint=? AND status!='closed'", (mint,)).fetchone()
            if not p: return await self.send(f"{nm} has no open position.")
            if p["status"] == "open" and p["mode"] == "PAPER": return await self.send("PAPER exits close on their own.")
            self.c.execute("UPDATE positions SET status='closed', closed_at=? WHERE id=?", (db.now(), p["id"]))
            return await self.send(f"{nm} closed")

    async def run(self):
        if not self.token: log.info("no TG_TOKEN, telegram off"); return
        while True:
            j = await self.call("getUpdates", timeout=30, offset=self.offset, allowed_updates=["message", "callback_query"])
            for u in j.get("result", []) if j.get("ok") else []:
                self.offset = u["update_id"] + 1
                msg = u.get("message") or {}; cb = u.get("callback_query")
                chat = (msg.get("chat") or {}).get("id") or ((cb or {}).get("message") or {}).get("chat", {}).get("id")
                if chat != self.owner: continue          # owner lock
                try:
                    if cb: await self.handle_cb(cb)
                    elif msg.get("text"): await self.handle_text(msg["text"])
                except Exception as e:
                    log.info(f"handler error {type(e).__name__}: {e}"); await self.send("Something went wrong, check the logs.")
            if not j.get("ok"): await asyncio.sleep(5)
