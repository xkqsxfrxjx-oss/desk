"""AGENT 3 · ANALYST. Builds a numbers-only state, gets 4 noul answers (Jev or rules), code applies the gate."""
import asyncio, hashlib, json, os, time
import bus, config, db, sources
from logs_util import logger
log = logger("analyst")
JEV_URL = "https://api.typesafe.ai/v1/systemone"
QUESTIONS = {
 "alive_6h": {"type": "noul", "instructions": "This coin is still actively traded 6 hours from now"},
 "organic": {"type": "noul", "instructions": "Most buyers in the last 30 minutes are separate real wallets"},
 "flush": {"type": "noul", "instructions": "Price just flushed down and buyers are absorbing it"},
 "chase": {"type": "noul", "instructions": "This entry is chasing a green candle that already ran"}}
NAMES = list(QUESTIONS)
clamp = lambda x, lo=0.0, hi=1.0: max(lo, min(hi, x))

def layer_val(audit, n): return next((l["value"] for l in audit["layers"] if l["n"] == n), "n/a")
def bundled_count(audit):
    v = layer_val(audit, 7)
    return 0 if v == "None" else int(v.split()[0]) if v.split()[0].isdigit() else 0

def build_state(scan, audit, d, max_chars=3000):
    f = lambda x: "n/a" if x is None else f"{x:,.0f}"
    p = lambda x: "n/a" if x is None else f"{x:+g}"
    dev = layer_val(audit, 3).split("%")[0]
    s = (f"Coin {scan.get('name')} on Solana, graduated {scan.get('ageMin')} min ago. Liquidity ${f(d.get('liquidity_usd'))}. "
         f"Market cap ${f(d.get('marketCap'))}.\n"
         f"Last 5 min: {d.get('buys_m5')} buys, {d.get('sells_m5')} sells, volume ${f(d.get('volume_m5'))}, price {p(d.get('priceChange_m5'))}%.\n"
         f"Last 1h: {d.get('buys_h1')} buys, {d.get('sells_h1')} sells, volume ${f(d.get('volume_h1'))}, price {p(d.get('priceChange_h1'))}%.\n"
         f"Top 10 hold {layer_val(audit, 4).replace('%', '')}%. Dev holds {dev}%, sold 0. LP {layer_val(audit, 5)}. "
         f"Bundled {layer_val(audit, 7)}. Delegations {layer_val(audit, 8)}.")
    return s[:max_chars]

def rules_answers(c, d, audit):
    R = lambda k: config.get(c, "analyst.rules." + k)
    org = clamp((d.get("buys_h1") or 0) / R("organic_buys_h1"))
    if bundled_count(audit) >= R("bundled_from"): org *= R("bundled_penalty")
    m5 = d.get("priceChange_m5") or 0
    flush = 1.0 if m5 <= -R("flush_drop_m5_pct") and (d.get("buys_m5") or 0) >= (d.get("sells_m5") or 0) else 0.5 if m5 < 0 else 0.0
    return {"alive_6h": clamp((d.get("volume_h1") or 0) / R("alive_volume_h1")), "organic": org, "flush": flush,
            "chase": clamp((d.get("priceChange_h1") or 0) / R("chase_h1_pct"))}

def gate(c, a, h1=None, A=None):
    """Code-only gate. Returns (score, passed, failed list). A: setting getter (shadow passes its own)."""
    A = A or (lambda k: config.get(c, "analyst." + k))
    score = round(100 * (a["alive_6h"] + a["organic"] + a["flush"] + (1 - a["chase"])) / 4)
    failed = []
    if a["alive_6h"] < A("min_alive_6h"): failed.append(f"alive_6h {a['alive_6h']:.2f}")
    if a["organic"] < A("min_organic"): failed.append(f"organic {a['organic']:.2f}")
    if a["chase"] > A("max_chase"): failed.append(f"chase {a['chase']:.2f}")
    if score < A("min_score"): failed.append(f"score {score}")
    mr = A("min_h1_rise_pct")
    if mr and (h1 is None or h1 < mr): failed.append(f"1h rise {h1 if h1 is not None else 'n/a'}% < {mr:g}%")
    return score, not failed, failed

class JevError(Exception): pass
async def ask_jev(c, state, key):
    body = {"model": "jev-latest", "state": state, "questions": QUESTIONS}
    deadline = time.monotonic() + config.get(c, "analyst.queue_429_s"); tries = 0
    while True:
        try:
            r = await sources.client().post(JEV_URL, json=body, headers={"Authorization": f"Bearer {key}"},
                                            timeout=config.get(c, "analyst.timeout_s"))
        except Exception as e:
            r = None; err = str(e)
        if r is not None and r.status_code == 429 and time.monotonic() < deadline:
            await asyncio.sleep(2); continue
        if r is not None and r.status_code == 200: return r.json()
        tries += 1
        if tries >= 2: raise JevError("no answer")
        await asyncio.sleep(2)

def read_answers(resp):
    a = {}
    for n in NAMES:
        v = ((resp.get("answers") or {}).get(n) or {}).get("noul")
        if not isinstance(v, (int, float)) or not 0 <= v <= 1: return None
        a[n] = float(v)
    return a

class Analyst:
    def __init__(self, c): self.c = c; self.done = set()
    async def analyse(self, scan, audit, fresh=None):
        mint = scan["mint"]
        if mint in self.done: return None
        self.done.add(mint)
        mode = config.get(self.c, "analyst.mode")
        if fresh is None:
            try: fresh = (await sources.dex_batch([mint])).get(mint) or {}
            except Exception: fresh = {}
        h1 = fresh.get("priceChange_h1") if fresh.get("priceChange_h1") is not None else scan.get("h1ChangePct")
        try:
            import shadow
            shadow.consider(self.c, scan, audit, fresh, mode, read_jev=None)
        except Exception as e: log.info(f"{mint} shadow error {type(e).__name__}: {e}")
        state = build_state(scan, audit, fresh, config.get(self.c, "analyst.max_state_chars"))
        model, tokens, answers, reason = "rules", 0, None, None
        if mode == "jev":
            try:
                resp = await ask_jev(self.c, state, os.environ.get("TYPESAFE_API_KEY", ""))
                model = resp.get("model") or "jev"; tokens = int(((resp.get("usage") or {}).get("input_tokens")) or 0)
                answers = read_answers(resp)
                if answers is None: reason = "bad answer"; log.info(f"{mint} bad answer raw={json.dumps(resp)[:1000]}")
            except JevError: reason = "no answer"; model = "jev"
        else:
            answers = rules_answers(self.c, fresh, audit)
        if answers:
            answers = {k: round(v, 4) for k, v in answers.items()}
            score, passed, failed = gate(self.c, answers, h1)
        else:
            score, passed, failed = None, False, [reason]
        out = {"agent": "analyst", "mint": mint, "answers": answers, "score": score, "passed": passed, "failed": failed,
               "model": model, "inputTokens": tokens}
        a = answers or {}
        self.c.execute("INSERT OR REPLACE INTO verdicts(mint,ts,alive_6h,organic,flush,chase,score,pass,reason,input_tokens) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (mint, db.now(), a.get("alive_6h"), a.get("organic"), a.get("flush"), a.get("chase"), score, int(passed),
                        failed[0] if failed else None, tokens))
        log.info(f"{mint} state={hashlib.sha256(state.encode()).hexdigest()[:12]} answers={a} score={score} "
                 f"{'PASS' if passed else 'REJECT ' + str(failed)} model={model} tokens={tokens}")
        bus.emit("verdict", out)
        if passed:
            await bus.executor.put({"scan": scan, "audit": audit, "analyst": out, "price": fresh.get("priceUsd")})
        else:
            who = "Analyst (rules)" if model == "rules" else "Analyst"
            self.c.execute("INSERT INTO activity(ts,kind,mint,agent,title,subtitle,value) VALUES(?,?,?,?,?,?,?)",
                           (db.now(), "rejected", mint, "analyst", f"Rejected {scan.get('name') or mint[:6]}", f"{who} · {failed[0]}", "Skipped"))
            self.c.execute("INSERT OR IGNORE INTO skips VALUES(?,?)", (mint, "report"))
        return out
    async def run(self):
        while True:
            while "analyst" in bus.PAUSED: await asyncio.sleep(2)
            j = await bus.analyst.get()
            try: await self.analyse(j["scan"], j["audit"])
            except Exception as e: log.info(f"{j['scan'].get('mint')} analyst crashed {type(e).__name__}: {e}")
