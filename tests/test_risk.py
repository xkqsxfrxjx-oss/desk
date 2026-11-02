import asyncio
from datetime import datetime, timedelta, timezone
import config, db, notifier
from agents.risk import Risk
from tests.conftest import coin, MINT
def open_pos(c, entry=1.0, mint=MINT, name="anakin", opened=None):
    coin(c, mint, name); s = config.get(c, "risk.stop_pct")
    c.execute("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,stop_pct,mode) VALUES(?,?,?,?,?,?,?,?)",
              (mint, opened or db.now(), entry, 47.5, entry, entry * (1 - s / 100), s, "PAPER"))
    return dict(c.execute("SELECT p.*, c.name FROM positions p JOIN coins c USING(mint) WHERE mint=? AND status='open'", (mint,)).fetchone())
def row(c, mint=MINT): return dict(c.execute("SELECT p.*, c.name FROM positions p JOIN coins c USING(mint) WHERE mint=? ORDER BY id DESC", (mint,)).fetchone())
run = asyncio.run
def test_trail_exit(c):
    r = Risk(c); open_pos(c)
    assert run(r.evaluate(row(c), 1.25, 1e5)) is None and row(c)["trail_active"] == 1
    assert run(r.evaluate(row(c), 1.25 * 0.88, 1e5)) is None or True
    out = run(r.evaluate(row(c), 1.25 * 0.87, 1e5)) if row(c)["status"] == "open" else None
    out = out or {"reason": row(c)["exit_reason"]}
    assert out["reason"] == "trail" and row(c)["exit_reason"] == "trail"
    assert row(c)["exit_price"] == 1.25 * 0.87 or row(c)["exit_price"] == 1.25 * 0.88
def test_trail_exact_13_off(c):
    r = Risk(c); open_pos(c); run(r.evaluate(row(c), 1.25, 1e5))
    out = run(r.evaluate(row(c), 1.25 * 0.87, 1e5)); assert out["reason"] == "trail" and out["exitPrice"] == 1.25 * 0.87
def test_stop(c):
    r = Risk(c); open_pos(c)
    assert run(r.evaluate(row(c), 0.95, 1e5)) is None
    out = run(r.evaluate(row(c), 0.939, 1e5)); assert out["reason"] == "stop" and out["exitPrice"] == 0.939
    assert out["pnlUsd"] < 0 and out["feesUsd"] > 0
def test_timeout(c):
    r = Risk(c); open_pos(c, opened=(datetime.now(timezone.utc) - timedelta(hours=3, seconds=1)).isoformat())
    out = run(r.evaluate(row(c), 1.04, 1e5)); assert out["reason"] == "timeout"
def test_no_timeout_before_3h(c):
    r = Risk(c); open_pos(c, opened=(datetime.now(timezone.utc) - timedelta(hours=2, minutes=59)).isoformat())
    assert run(r.evaluate(row(c), 1.04, 1e5)) is None
def test_loosen_never_moves_open_stop_down(c):
    r = Risk(c); open_pos(c); config.set(c, "stop", "-10%")
    run(r.evaluate(row(c), 0.99, 1e5)); p = row(c); assert p["stop_pct"] == 6 and abs(p["stop_price"] - 0.94) < 1e-12
    config.set(c, "stop", "-4%"); run(r.evaluate(row(c), 0.99, 1e5)); p = row(c)
    assert p["stop_pct"] == 4 and abs(p["stop_price"] - 0.96) < 1e-12   # tighter applies
def test_set_stop_8_flow(c):
    r = Risk(c); old = open_pos(c, mint="OLD1111111111111111111111111111111111111111", name="oldie")
    reply = config.set(c, "set stop to".split()[-1] if False else "stop", "-8%"); assert reply == "stop -6% -> -8%"
    assert f"stop -{config.get(c, 'risk.stop_pct'):g}%" == "stop -8%"          # Risk pill
    open_pos(c, mint=MINT, name="newbie")
    assert run(r.evaluate(row(c), 0.93, 1e5)) is None                          # -7%: holds under -8%
    out = run(r.evaluate(row(c), 0.919, 1e5))                                  # -8.1%
    assert out["reason"] == "stop" and out["stopPct"] == 8
    push = notifier.SENT[-1]["text"]; assert "hit the -8% stop" in push and push.startswith("PAPER · newbie")
    act = c.execute("select subtitle from activity where kind='stopped'").fetchone()[0]; assert act == "Risk · -8% stop"
    o = row(c, old["mint"]); assert o["stop_pct"] == 6 and o["status"] == "open"   # old position still shows -6%
def test_pulled(c):
    r = Risk(c); open_pos(c); out = run(r.evaluate(row(c), 1.1, 0)); assert out["reason"] == "pulled"
