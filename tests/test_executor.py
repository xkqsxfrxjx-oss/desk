import asyncio
import config, db, notifier
from agents.executor import Executor, size_order, stack
from tests.conftest import coin, MINT
JOB = {"scan": {"mint": MINT, "name": "anakin", "liquidityUsd": 50000}, "analyst": {"score": 74}, "price": 1.0}
def test_sizes(c):
    assert stack(c) == 200
    size, why, cap, raw = size_order(c, 200, 200, 1e6); assert raw == 16 and size == 47.5 and cap == "bumped"
    config.set(c, "below_min", "skip"); size, why, *_ = size_order(c, 200, 200, 1e6); assert size is None and why == "under $47.50"
def test_pool_cap(c):
    size, why, cap, raw = size_order(c, 1_000_000, 1_000_000, 40000); assert size == 800 and cap == "max_pool_pct"
def test_no_free_stack(c):
    assert size_order(c, 200, 40, 1e6)[1] == "no free stack"
def test_ticket_check_warns(c):
    ok, msg = config.ticket_check(c, 200); assert ok and msg == "tickets bumped to $47.50 = 23.8% of stack"
    config.set(c, "below_min", "skip"); ok, msg = config.ticket_check(c, 200)
    assert not ok and msg.startswith("every coin will be skipped, stack under $593.75")
def test_paper_fill_and_push(c):
    coin(c); out = asyncio.run(Executor(c).handle(JOB, fresh={"priceUsd": 1.0, "liquidity_usd": 50000}))
    assert out["status"] == "bought" and out["sizeUsd"] == 47.5 and "r=savipww" in out["link"]
    t = notifier.SENT[-1]["text"]; assert t.startswith("PAPER · Buy anakin · $47.50 · 23.75% of stack") and "stop -6% · trail 12%" in t
    assert [b[0] for b in notifier.SENT[-1]["buttons"]] == ["Buy on FOMO", "Bought", "Skip"]
    assert c.execute("select count(*) from positions where status='open'").fetchone()[0] == 1
    assert asyncio.run(Executor(c).handle(JOB, fresh={"priceUsd": 1.0, "liquidity_usd": 50000})) is None   # 1 push per coin
def test_skip_mode_skips(c):
    coin(c); config.set(c, "below_min", "skip")
    out = asyncio.run(Executor(c).handle(JOB, fresh={"priceUsd": 1.0, "liquidity_usd": 50000})); assert out["status"] == "skipped" and out["reason"] == "under $47.50"
def test_rechecks(c):
    coin(c); assert asyncio.run(Executor(c).handle(JOB, fresh={"priceUsd": 1.0, "liquidity_usd": 39000}))["reason"] == "liquidity dropping"
def test_ran(c):
    coin(c); assert asyncio.run(Executor(c).handle(JOB, fresh={"priceUsd": 1.16, "liquidity_usd": 50000}))["reason"] == "ran before the push"
def test_no_price(c):
    coin(c); assert asyncio.run(Executor(c).handle(JOB, fresh={"liquidity_usd": 50000}))["reason"] == "no price"
