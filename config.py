"""Settings (STEP 10): defaults, ranges, aliases, validation, change log in db."""
import db
# key: (default, min, max)   strings: (default, allowed set or None, None)
SPEC = {
 "scanner.min_liquidity_usd": (40000, 1000, 10_000_000), "scanner.max_top10_pct": (25, 1, 100),
 "scanner.max_h1_change_pct": (80, 1, 10000), "scanner.poll_s": (60, 15, 600),
 "scanner.min_pool_age_min": (10, 0, 240), "scanner.max_wait_min": (60, 5, 720),
 "scanner.runner_h24_pct": (300, 10, 100000), "scanner.max_dex_rpm": (250, 10, 290),
 "scanner.ws_silence_s": (120, 30, 900),
 "auditor.enabled": (True, None, None), "auditor.max_dev_pct": (5, 0, 100), "auditor.max_top10_pct": (25, 1, 100),
 "auditor.min_lp_locked_pct": (99, 0, 100), "auditor.min_pool_age_min": (10, 0, 240),
 "auditor.max_bundled": (5, 1, 1000), "auditor.max_delegated_accounts": (10, 1, 100000),
 "auditor.retries": (3, 1, 10), "auditor.retry_wait_s": (2, 0, 30), "auditor.max_liq_drop_pct": (50, 1, 100),
 "analyst.mode": ("rules", {"jev", "rules"}, None), "analyst.min_alive_6h": (0.70, 0, 1),
 "analyst.min_organic": (0.65, 0, 1), "analyst.max_chase": (0.30, 0, 1), "analyst.min_score": (70, 0, 100),
 "analyst.timeout_s": (10, 2, 60), "analyst.max_state_chars": (3000, 500, 10000), "analyst.queue_429_s": (60, 0, 600),
 "analyst.rules.alive_volume_h1": (25000, 1, 10_000_000), "analyst.rules.organic_buys_h1": (150, 1, 100000),
 "analyst.rules.bundled_penalty": (0.5, 0, 1), "analyst.rules.bundled_from": (3, 1, 1000),
 "analyst.rules.flush_drop_m5_pct": (5, 0.1, 100), "analyst.rules.chase_h1_pct": (80, 1, 10000),
 "executor.stack_pct": (8, 0.1, 100), "executor.max_pool_pct": (2, 0.01, 100), "executor.min_ticket_usd": (47.50, 5, 100000),
 "executor.below_min": ("bump", {"bump", "skip"}, None), "executor.recheck_liq_drop_pct": (20, 1, 100),
 "executor.recheck_price_up_pct": (15, 1, 1000), "executor.confirm_window_min": (5, 1, 60),
 "risk.poll_s": (15, 5, 300), "risk.stop_pct": (6, 0.5, 90), "risk.trail_start_pct": (20, 1, 1000),
 "risk.trail_pct": (12, 0.5, 90), "risk.timeout_h": (3, 0.25, 72), "risk.timeout_min_gain_pct": (5, -50, 1000),
 "risk.confirm_window_min": (2, 1, 60), "risk.no_price_polls": (4, 1, 100), "risk.backoff_429_s": (30, 1, 600),
 "desk.mode": ("PAPER", {"PAPER", "LIVE"}, None), "desk.paper_start_stack": (200, 1, 10_000_000),
 "desk.live_stack": (0, 0, 100_000_000), "desk.report_time": ("08:00", None, None),
 "desk.notifier": ("telegram", {"telegram", "webpush", "channel"}, None),
 "desk.rpc_url": ("https://api.mainnet-beta.solana.com", None, None), "desk.push_rejects": (False, None, None),
 "desk.fees_ref_discount": (0.10, 0, 1), "desk.fomo_handle": ("rangeri", None, None),
}
ALIASES = {"stop": "risk.stop_pct", "trail": "risk.trail_pct", "trail start": "risk.trail_start_pct",
 "timeout": "risk.timeout_h", "stack pct": "executor.stack_pct", "ticket": "executor.min_ticket_usd",
 "below min": "executor.below_min", "min liquidity": "scanner.min_liquidity_usd", "min score": "analyst.min_score",
 "mode": "desk.mode", "rpc": "desk.rpc_url", "report time": "desk.report_time"}
SHORT = {"risk.stop_pct": "stop", "risk.trail_pct": "trail"}

class SettingError(ValueError): pass

def resolve(name: str) -> str:
    n = name.strip().lower().replace("_", " ")
    if name in SPEC: return name
    if n in ALIASES: return ALIASES[n]
    hits = [k for k in SPEC if k.split(".")[-1].replace("_", " ") == n]
    if len(hits) == 1: return hits[0]
    raise SettingError(f"unknown setting '{name}'" + (f", did you mean {', '.join(hits)}" if hits else ""))

def _coerce(key, raw):
    d, lo, hi = SPEC[key]
    if isinstance(d, bool):
        v = str(raw).lower()
        if v not in ("true", "false", "1", "0", "on", "off"): raise SettingError(f"{key} must be true or false")
        return v in ("true", "1", "on")
    if isinstance(d, (int, float)):
        try: v = float(str(raw).replace("%", "").replace("$", "").replace(",", ""))
        except ValueError: raise SettingError(f"{key} must be a number")
        if key == "risk.stop_pct": v = abs(v)
        if not (lo <= v <= hi): raise SettingError(f"{key} must be between {lo} and {hi}")
        return int(v) if isinstance(d, int) and v.is_integer() else v
    v = str(raw)
    if isinstance(lo, frozenset) or type(lo).__name__ == "set":
        v = v.upper() if key == "desk.mode" else v.lower()
        if v not in lo: raise SettingError(f"{key} must be one of {', '.join(sorted(lo))}")
    return v

def get(c, name):
    key = resolve(name)
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return SPEC[key][0] if r is None else _coerce(key, r[0])

def all_settings(c):
    return {k: get(c, k) for k in SPEC}

def fmt(key, v):
    if key == "risk.stop_pct": return f"-{v:g}%"
    if isinstance(v, float): return f"{v:g}"
    return str(v)

def set(c, name, raw, who="owner"):
    """Validate + store + change_log. Returns reply text like 'stop -6% -> -8%'."""
    key = resolve(name)
    new = _coerce(key, raw)
    if key == "desk.mode" and new == "LIVE" and who != "owner-typed-LIVE":
        raise SettingError("switching to LIVE needs you to type LIVE")
    old = get(c, key)
    db.set_setting(c, key, new if not isinstance(new, bool) else str(new).lower(), who)
    return f"{SHORT.get(key, key)} {fmt(key, old)} -> {fmt(key, new)}"

def min_stack(c):
    return round(get(c, "executor.min_ticket_usd") / (get(c, "executor.stack_pct") / 100), 2)

def ticket_check(c, stack):
    """STEP 10 ticket check. Returns (ok, message|None)."""
    ms = min_stack(c); mt = get(c, "executor.min_ticket_usd")
    if stack >= ms: return True, None
    if get(c, "executor.below_min") == "bump":
        return True, f"tickets bumped to ${mt:.2f} = {round(100 * mt / stack, 1):g}% of stack"
    return False, (f"every coin will be skipped, stack under ${ms:,.2f}. "
                   "Switch below_min to bump or raise the stack.")
