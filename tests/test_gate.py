import asyncio
import config, db
from agents import analyst as A
from tests.conftest import coin, MINT
TH = {"alive_6h": 0.70, "organic": 0.65, "flush": 0.55, "chase": 0.30}   # score = round(100*(0.7+0.65+0.55+0.7)/4)=65 -> use flush to hit 70
def answers(**kw):
    a = {"alive_6h": 0.70, "organic": 0.65, "flush": 0.75, "chase": 0.30}; a.update(kw); return a
def test_at_threshold_passes(c):
    s, ok, f = A.gate(c, answers()); assert s == 70 and ok and not f
def test_each_rejects(c):
    assert A.gate(c, answers(alive_6h=0.69))[2][0] == "alive_6h 0.69"
    assert A.gate(c, answers(organic=0.64))[2][0] == "organic 0.64"
    assert A.gate(c, answers(chase=0.31))[2][0] == "chase 0.31"
    s, ok, f = A.gate(c, answers(flush=0.71)); assert s == 69 and not ok and f == ["score 69"]
AUDIT = {"layers": [{"n": i, "value": v} for i, v in enumerate(["Revoked", "Revoked", "0.9% · sold 0", "16.8%", "100% locked", "43m", "None", "None"], 1)]}
SCAN = {"mint": MINT, "name": "anakin", "ageMin": 30, "liquidityUsd": 50000}
def test_jev_mode(c, monkeypatch):
    config.set(c, "analyst.mode", "jev"); coin(c)
    async def fake(c_, state, key):
        assert "buy " not in state.lower().replace("buys", "") and "0.70" not in state and len(state) <= 3000
        return {"model": "jev-latest", "usage": {"input_tokens": 321}, "answers": {k: {"noul": v} for k, v in answers(organic=0.64).items()}}
    monkeypatch.setattr(A, "ask_jev", fake)
    out = asyncio.run(A.Analyst(c).analyse(SCAN, AUDIT, fresh={"priceUsd": 1}))
    assert not out["passed"] and out["failed"][0] == "organic 0.64" and out["inputTokens"] == 321 and out["model"] == "jev-latest"
    assert c.execute("select subtitle from activity").fetchone()[0] == "Analyst · organic 0.64"
def test_jev_error_no_fallback(c, monkeypatch):
    config.set(c, "analyst.mode", "jev"); coin(c)
    async def boom(*a): raise A.JevError("no answer")
    monkeypatch.setattr(A, "ask_jev", boom)
    out = asyncio.run(A.Analyst(c).analyse(SCAN, AUDIT, fresh={}))
    assert not out["passed"] and out["failed"] == ["no answer"]
def test_jev_bad_answer(c, monkeypatch):
    config.set(c, "analyst.mode", "jev"); coin(c)
    async def bad(*a): return {"model": "jev-latest", "answers": {"alive_6h": {"noul": 1.4}}}
    monkeypatch.setattr(A, "ask_jev", bad)
    assert asyncio.run(A.Analyst(c).analyse(SCAN, AUDIT, fresh={}))["failed"] == ["bad answer"]
def dex(vol_h1, buys_h1, m5, b5, s5, h1):
    return {"volume_h1": vol_h1, "buys_h1": buys_h1, "priceChange_m5": m5, "buys_m5": b5, "sells_m5": s5, "priceChange_h1": h1, "priceUsd": 1}
def test_rules_thresholds(c):
    # alive 17500/25000=0.70, organic 97.5/150=0.65 -> use 98 buys=0.6533, flush 1, chase 24/80=0.30
    a = A.rules_answers(c, dex(17500, 98, -6, 10, 5, 24), AUDIT); s, ok, f = A.gate(c, a)
    assert a["alive_6h"] == 0.70 and a["chase"] == 0.30 and a["flush"] == 1.0 and ok, (a, s, f)
    assert A.gate(c, A.rules_answers(c, dex(17250, 98, -6, 10, 5, 24), AUDIT))[2][0] == "alive_6h 0.69"
    assert A.gate(c, A.rules_answers(c, dex(17500, 96, -6, 10, 5, 24), AUDIT))[2][0] == "organic 0.64"
    assert A.gate(c, A.rules_answers(c, dex(17500, 98, -6, 10, 5, 24.8), AUDIT))[2][0] == "chase 0.31"
    a = A.rules_answers(c, dex(17500, 98, 0, 10, 5, 24), AUDIT)   # flush 0 -> score round(100*(.7+.6533+0+.7)/4)=51
    assert A.gate(c, a)[2] == [f"score {A.gate(c, a)[0]}"]
def test_rules_bundled_penalty_and_flush(c):
    au = {"layers": [{"n": 7, "value": "3 bundled wallets"}]}
    assert A.rules_answers(c, dex(0, 150, -1, 0, 9, 0), au)["organic"] == 0.5
    assert A.rules_answers(c, dex(0, 150, -1, 0, 9, 0), au)["flush"] == 0.5
    assert A.rules_answers(c, dex(0, 150, -5, 9, 9, 0), au)["flush"] == 1.0
def test_rules_activity_row(c):
    coin(c)
    out = asyncio.run(A.Analyst(c).analyse(SCAN, AUDIT, fresh=dex(17250, 98, -6, 10, 5, 24)))
    assert out["model"] == "rules" and out["inputTokens"] == 0 and not out["passed"]
    assert c.execute("select subtitle,value from activity").fetchone()[:] == ("Analyst (rules) · alive_6h 0.69", "Skipped")
    assert asyncio.run(A.Analyst(c).analyse(SCAN, AUDIT, fresh={})) is not None   # new instance; same instance never re-asks:
    a = A.Analyst(c); asyncio.run(a.analyse(SCAN, AUDIT, fresh={})); assert asyncio.run(a.analyse(SCAN, AUDIT, fresh={})) is None
