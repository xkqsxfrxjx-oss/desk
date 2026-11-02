"""Shadow rulesets: evaluate alternative rules on the same coin stream and record HYPOTHETICAL paper trades
in shadow_positions. Never pushes Telegram buttons, never touches positions/signals, never places orders.
Same fee model (fees.py) as the live paper desk."""
from datetime import datetime, timezone
import config, db, fees
from agents.executor import size_order
from logs_util import logger
log = logger("shadow")

# Rules in force before 2026-11-02 (Matias approved the new set and asked to compare against these).
RULESETS = {"old": {
    "scanner.min_liquidity_usd": 25000, "scanner.max_h1_change_pct": 80,
    "analyst.max_chase": 0.30, "analyst.rules.chase_h1_pct": 80, "analyst.min_h1_rise_pct": 0,
    "risk.stop_pct": 6, "risk.trail_enabled": True, "risk.trail_start_pct": 20, "risk.trail_pct": 12,
    "risk.take_profit_pct": 0, "risk.timeout_h": 3}}

def getter(c, rs):
    o = RULESETS[rs]
    return lambda k: o[k] if k in o else config.get(c, k)

def stack(c, rs):
    pnl = c.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM shadow_positions WHERE ruleset=? AND status='closed'", (rs,)).fetchone()[0]
    return round(config.get(c, "desk.paper_start_stack") + pnl, 2)

def consider(c, scan, audit, fresh, mode=None, **_):
    """Called by the Analyst for every coin that reached it (passed scanner with live rules + Auditor)."""
    if not config.get(c, "shadow.enabled"): return []
    from agents.analyst import rules_answers, gate
    out = []
    for rs in RULESETS:
        mint = scan["mint"]
        if c.execute("SELECT 1 FROM shadow_decisions WHERE ruleset=? AND mint=?", (rs, mint)).fetchone(): continue
        G = getter(c, rs); reason = None
        liq = scan.get("liquidityUsd"); h1s = scan.get("h1ChangePct")
        if liq is None or liq < G("scanner.min_liquidity_usd"): reason = f"scanner liq ${(liq or 0) / 1000:.1f}K"
        elif h1s is not None and h1s > G("scanner.max_h1_change_pct"): reason = f"scanner +{h1s:.0f}% in 1h"
        else:
            d = dict(fresh)
            # rules_answers reads chase_h1_pct from config; rescale chase with the ruleset's value
            a = rules_answers(c, d, audit)
            a["chase"] = max(0.0, min(1.0, (d.get("priceChange_h1") or 0) / G("analyst.rules.chase_h1_pct")))
            h1 = d.get("priceChange_h1") if d.get("priceChange_h1") is not None else h1s
            _, ok, failed = gate(c, {k: round(v, 4) for k, v in a.items()}, h1, A=lambda k: G("analyst." + k))
            if not ok: reason = "analyst " + failed[0]
        price = fresh.get("priceUsd")
        if reason is None and not price: reason = "no price"
        size = None
        if reason is None:
            stk = stack(c, rs)
            free = stk - c.execute("SELECT COALESCE(SUM(size_usd),0) FROM shadow_positions WHERE ruleset=? AND status='open'", (rs,)).fetchone()[0]
            size, why, _, _ = size_order(c, stk, free, fresh.get("liquidity_usd"))
            if why: reason = "executor " + why
        c.execute("INSERT OR IGNORE INTO shadow_decisions VALUES(?,?,?,?,?)", (rs, mint, db.now(), int(reason is None), reason))
        if reason is None:
            s = G("risk.stop_pct")
            c.execute("""INSERT OR IGNORE INTO shadow_positions(ruleset,mint,opened_at,entry_price,size_usd,peak_price,stop_price,stop_pct,
                trail_start_pct,trail_pct,take_profit_pct,timeout_h,timeout_min_gain_pct) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rs, mint, db.now(), price, size, price, price * (1 - s / 100), s,
                 G("risk.trail_start_pct") if G("risk.trail_enabled") else None, G("risk.trail_pct"),
                 G("risk.take_profit_pct") or None, G("risk.timeout_h"), G("risk.timeout_min_gain_pct")))
        log.info(f"{mint} shadow[{rs}] {'BUY' if reason is None else 'skip ' + reason} size={size}")
        out.append((rs, reason))
    return out

def open_rows(c):
    return [dict(r) for r in c.execute("SELECT * FROM shadow_positions WHERE status='open'")]

def evaluate(c, p, price, liq, now=None):
    """Mirror of Risk.evaluate for one shadow row. Returns exit reason or None. No notifications."""
    now = now or datetime.now(timezone.utc)
    if liq is not None and liq <= 0:
        last = c.execute("SELECT price FROM prices WHERE mint=? AND price IS NOT NULL ORDER BY ts DESC LIMIT 1", (p["mint"],)).fetchone()
        return close(c, p, "pulled", price or (last[0] if last else p["peak_price"]))
    peak = max(p["peak_price"], price); e = p["entry_price"]; action = None
    c.execute("UPDATE shadow_positions SET peak_price=? WHERE id=?", (peak, p["id"]))
    if price <= p["stop_price"]: action = "stop"
    elif p["take_profit_pct"] and price >= e * (1 + p["take_profit_pct"] / 100): action = "take_profit"
    else:
        ta = p["trail_active"]
        if p["trail_start_pct"] is not None and not ta and price >= e * (1 + p["trail_start_pct"] / 100):
            ta = 1; c.execute("UPDATE shadow_positions SET trail_active=1 WHERE id=?", (p["id"],))
        if ta and price <= peak * (1 - p["trail_pct"] / 100): action = "trail"
        elif (now - datetime.fromisoformat(p["opened_at"].replace("Z", "+00:00"))).total_seconds() >= p["timeout_h"] * 3600 \
                and price < e * (1 + p["timeout_min_gain_pct"] / 100): action = "timeout"
    return close(c, p, action, price) if action else None

def close(c, p, reason, price):
    value = p["size_usd"] * price / p["entry_price"]
    fee = fees.round_trip(p["size_usd"], value, config.get(c, "desk.fees_ref_discount"))
    pnl = round(value - p["size_usd"] - fee, 2)
    c.execute("UPDATE shadow_positions SET status='closed', exit_price=?, exit_reason=?, pnl_usd=?, fees_usd=?, closed_at=? WHERE id=?",
              (price, reason, pnl, round(fee, 2), db.now(), p["id"]))
    log.info(f"{p['mint']} shadow[{p['ruleset']}] EXIT {reason} price={price} pnl={pnl}")
    return reason

def summarize(rows):
    """rows: closed trades with pnl_usd,size_usd. -> trades, wins, avgPctNet, totalUsdNet, bestTradeShare."""
    n = len(rows); tot = round(sum(r["pnl_usd"] for r in rows), 2)
    pos = [r["pnl_usd"] for r in rows if r["pnl_usd"] > 0]
    return {"trades": n, "wins": len(pos),
            "avgPctNet": round(sum(100 * r["pnl_usd"] / r["size_usd"] for r in rows) / n, 2) if n else None,
            "totalUsdNet": tot,
            "bestTradeShare": round(max(pos) / sum(pos), 3) if pos else None}

def compare(c, since):
    new = [dict(r) for r in c.execute("SELECT pnl_usd,size_usd FROM positions WHERE mode='PAPER' AND status='closed' AND pnl_usd IS NOT NULL AND opened_at>=?", (since,))]
    out = {"new": summarize(new)}
    for rs in RULESETS:
        rows = [dict(r) for r in c.execute("SELECT pnl_usd,size_usd FROM shadow_positions WHERE ruleset=? AND status='closed' AND opened_at>=?", (rs, since))]
        out[rs] = summarize(rows)
        out[rs]["open"] = c.execute("SELECT COUNT(*) FROM shadow_positions WHERE ruleset=? AND status='open'", (rs,)).fetchone()[0]
    out["new"]["open"] = c.execute("SELECT COUNT(*) FROM positions WHERE mode='PAPER' AND status='open'").fetchone()[0]
    return out

def compare_text(c, since):
    d = compare(c, since)
    f = lambda k, s: (f"{k.upper()}: {s['trades']} trades, {s['wins']} wins, avg {s['avgPctNet'] if s['avgPctNet'] is not None else '-'}% net, "
                      f"total ${s['totalUsdNet']:+,.2f}, {s['open']} open")
    return "PAPER · rules compare since " + since[:16].replace("T", " ") + " UTC\n" + "\n".join(f(k, d[k]) for k in ("new", "old"))
