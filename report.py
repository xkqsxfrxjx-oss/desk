"""STEP 12 morning report data + last Page link. The night-report routine builds the Page from build().
CLI: python report.py json [since_iso] | save-link URL | last-link | clear-skips"""
import json, sys
from datetime import datetime, timedelta, timezone
import config, db, links, shadow
KEY = "desk.last_report_url"

def save_link(c, url):
    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?,?)", (KEY, url, db.now()))
def last_link(c):
    r = c.execute("SELECT value FROM settings WHERE key=?", (KEY,)).fetchone()
    return r[0] if r else None
def clear_skips(c):
    n = c.execute("SELECT COUNT(*) FROM skips").fetchone()[0]; c.execute("DELETE FROM skips"); return n

def build(c, since=None):
    since = since or (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds").replace("+00:00", "Z")
    R = lambda q, a=(): [dict(r) for r in c.execute(q, a)]
    name = lambda m: (R("SELECT COALESCE(name,symbol) n FROM coins WHERE mint=?", (m,)) or [{"n": None}])[0]["n"] or m[:6]
    trades = R("SELECT * FROM positions WHERE opened_at>=? AND status='closed' ORDER BY pnl_usd", (since,))
    for t in trades:
        t.update(name=name(t["mint"]), link=links.coin_url(t["mint"], "solana"),
                 pct=round(100 * t["pnl_usd"] / t["size_usd"], 2) if t["pnl_usd"] is not None else None)
    kills = R("SELECT reason, mint, ts FROM scans WHERE ts>=? AND verdict='kill' ORDER BY ts", (since,))
    by_reason = {}
    for k in kills:
        key = "liquidity" if k["reason"].startswith("liq") else "top 10" if k["reason"].startswith("top 10") else \
              "1h pump" if "in 1h" in k["reason"] else "copycat" if k["reason"].startswith("copycat") else k["reason"]
        by_reason.setdefault(key, []).append({"name": name(k["mint"]), "reason": k["reason"], "ts": k["ts"], "link": links.coin_url(k["mint"], "solana")})
    refusals = R("SELECT mint, layer, name, value_text, ts FROM audits WHERE ts>=? AND pass=0 ORDER BY layer, ts", (since,))
    for r in refusals: r.update(coin=name(r["mint"]), link=links.coin_url(r["mint"], "solana"))
    rejects = R("SELECT mint, reason, score, ts FROM verdicts WHERE ts>=? AND pass=0 ORDER BY ts", (since,))
    for r in rejects: r.update(coin=name(r["mint"]), link=links.coin_url(r["mint"], "solana"))
    tokens = c.execute("SELECT COALESCE(SUM(input_tokens),0) FROM verdicts WHERE ts>=?", (since,)).fetchone()[0]
    seen = R("SELECT mint FROM coins WHERE migrated_at>=?", (since,))
    return {
        "since": since, "generated": db.now(), "mode": config.get(c, "desk.mode"),
        "layer8Kills": sum(1 for r in refusals if r["layer"] == 8 and r["value_text"].startswith("no data")),
        "red": [t for t in trades if (t["pnl_usd"] or 0) < 0], "green": [t for t in trades if (t["pnl_usd"] or 0) >= 0],
        "coinsSeen": [{"name": name(s["mint"]), "link": links.coin_url(s["mint"], "solana")} for s in seen],
        "scannerKills": {k: {"count": len(v), "coins": v} for k, v in by_reason.items()},
        "auditorRefusals": refusals, "analystRejects": rejects,
        "jev": {"mode": config.get(c, "analyst.mode"), "inputTokens": tokens},
        "feesUsd": round(sum(t["fees_usd"] or 0 for t in trades), 2),
        "pnlUsd": round(sum(t["pnl_usd"] or 0 for t in trades), 2),
        "rulesCompare": shadow.compare(c, since),
        "rulesCompareStart": c.execute("SELECT MIN(ts) FROM change_log WHERE who='matias'").fetchone()[0],
        "footer": "New to FOMO? " + links.SIGNUP_URL}

if __name__ == "__main__":
    c = db.connect(); a = sys.argv[1:] or ["json"]
    if a[0] == "json": print(json.dumps(build(c, a[1] if len(a) > 1 else None), indent=1, ensure_ascii=False))
    elif a[0] == "save-link": save_link(c, a[1]); print("saved")
    elif a[0] == "last-link": print(last_link(c) or "none")
    elif a[0] == "clear-skips": print("cleared", clear_skips(c))
