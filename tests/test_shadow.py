import asyncio
from datetime import datetime, timedelta, timezone
import config, db, notifier, shadow, report
from agents.analyst import gate
from agents.risk import Risk
from tests.conftest import coin, MINT
from tests.test_risk import open_pos, row
run = asyncio.run
AUD = {"layers": [{"n": 7, "value": "None"}, {"n": 3, "value": "0%"}, {"n": 4, "value": "10%"}, {"n": 5, "value": "100%"}, {"n": 8, "value": "0"}]}
def new_rules(c):
    for k, v in [("scanner.max_h1_change_pct", 400), ("analyst.max_chase", 1.0), ("analyst.rules.chase_h1_pct", 400),
                 ("analyst.min_h1_rise_pct", 80), ("scanner.min_liquidity_usd", 15000), ("risk.stop_pct", 12),
                 ("risk.take_profit_pct", 40), ("risk.trail_enabled", "false"), ("risk.timeout_h", 2)]:
        config.set(c, k, v, who="matias")
def fresh(h1, price=1.0):
    return {"priceUsd": price, "priceChange_h1": h1, "priceChange_m5": -6, "buys_m5": 10, "sells_m5": 5,
            "buys_h1": 300, "volume_h1": 50000, "liquidity_usd": 30000}
def scan(h1, liq=30000, mint=MINT): return {"mint": mint, "liquidityUsd": liq, "h1ChangePct": h1}
GOOD = {"alive_6h": 1, "organic": 1, "flush": 1, "chase": 0}

def test_min_rise_rule(c):
    new_rules(c)
    assert gate(c, GOOD, 50)[1] is False and "1h rise" in gate(c, GOOD, 50)[2][0]
    assert gate(c, GOOD, 120)[1] is True
    assert gate(c, dict(GOOD, chase=0.9), 300)[1] is True       # chase penalty off (max 1.0)

def test_take_profit_replaces_trail(c):
    new_rules(c); r = Risk(c); open_pos(c)
    assert row(c)["stop_pct"] == 12
    assert run(r.evaluate(row(c), 1.25, 1e5)) is None and row(c)["trail_active"] == 0
    out = run(r.evaluate(row(c), 1.41, 1e5)); assert out["reason"] == "take_profit" and row(c)["exit_reason"] == "take_profit"

def test_new_timeout_2h(c):
    new_rules(c); r = Risk(c); open_pos(c, opened=(datetime.now(timezone.utc) - timedelta(hours=2, seconds=1)).isoformat())
    assert run(r.evaluate(row(c), 1.01, 1e5))["reason"] == "timeout"

def test_shadow_old_buys_what_new_rejects(c):
    new_rules(c); coin(c)
    res = shadow.consider(c, scan(20), AUD, fresh(20))
    assert res == [("old", None)]
    p = dict(c.execute("SELECT * FROM shadow_positions").fetchone())
    assert p["ruleset"] == "old" and p["stop_pct"] == 6 and p["trail_start_pct"] == 20 and p["timeout_h"] == 3
    assert c.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0 and not notifier.SENT

def test_shadow_old_rejects_pump_and_low_liq(c):
    new_rules(c); coin(c); coin(c, "B" * 44, "b")
    assert shadow.consider(c, scan(150), AUD, fresh(150))[0][1].startswith("scanner +150%")
    assert shadow.consider(c, scan(100, 20000, "B" * 44), AUD, fresh(100))[0][1].startswith("scanner liq")

def test_shadow_exits_silently_with_fees(c):
    new_rules(c); coin(c); shadow.consider(c, scan(20), AUD, fresh(20))
    p = shadow.open_rows(c)[0]
    assert shadow.evaluate(c, p, 1.3, 1e5) is None
    p = shadow.open_rows(c)[0]; assert p["trail_active"] == 1
    assert shadow.evaluate(c, p, 1.3 * 0.87, 1e5) == "trail"
    q = dict(c.execute("SELECT * FROM shadow_positions").fetchone())
    assert q["status"] == "closed" and q["fees_usd"] > 0 and not notifier.SENT

def test_risk_tick_skips_push_for_shadow(c, monkeypatch):
    new_rules(c); coin(c); shadow.consider(c, scan(20), AUD, fresh(20))
    import sources
    async def fake(m): return {x: {"priceUsd": 0.9, "liquidity_usd": 1e5, "volume_m5": 1} for x in m}
    monkeypatch.setattr(sources, "dex_batch", fake)
    run(Risk(c).tick())
    assert dict(c.execute("SELECT * FROM shadow_positions").fetchone())["exit_reason"] == "stop" and not notifier.SENT

def test_report_compare(c):
    new_rules(c); coin(c); shadow.consider(c, scan(20), AUD, fresh(20))
    shadow.evaluate(c, shadow.open_rows(c)[0], 0.5, 1e5)
    d = report.build(c)["rulesCompare"]
    assert set(d) == {"new", "old"} and d["old"]["trades"] == 1 and d["old"]["wins"] == 0 and d["new"]["trades"] == 0
    for k in ("trades", "wins", "avgPctNet", "totalUsdNet", "bestTradeShare", "open"): assert k in d["old"]
    assert "NEW" in shadow.compare_text(c, "1970-01-01T00:00:00Z")

def test_migration_allows_take_profit(tmp_path):
    import sqlite3
    p = str(tmp_path / "old.db"); x = sqlite3.connect(p)
    x.executescript(db.SCHEMA.replace(",'take_profit'", "")); x.execute("INSERT INTO coins(mint,migrated_at) VALUES('m','t')")
    x.execute("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,stop_pct,mode) VALUES('m','t',1,1,1,1,6,'PAPER')"); x.commit(); x.close()
    c = db.connect(p); c.execute("UPDATE positions SET exit_reason='take_profit'")
    assert c.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 1
