"""STEP 13 item 1b: a PAPER push through every configured channel carries the exact links.py URL."""
import asyncio, json, os
import links, notifier
from agents.executor import Executor
from tests.conftest import coin, MINT
class FakeTG:
    def __init__(self): self.calls = []
    async def send(self, text, buttons=None):
        from telegram import Telegram
        kb = Telegram.kb(None, buttons); self.calls.append({"text": text, "reply_markup": kb}); return True
def test_paper_push_through_telegram_carries_exact_url(c):
    fake = FakeTG(); notifier.BACKEND = fake
    try:
        coin(c); out = asyncio.run(Executor(c).handle({"scan": {"mint": MINT, "name": "anakin", "liquidityUsd": 50000},
                     "analyst": {"score": 74}, "price": 1.0}, fresh={"priceUsd": 1.0, "liquidity_usd": 50000}))
    finally: notifier.BACKEND = None
    assert len(fake.calls) == 1
    m = fake.calls[0]; btn = m["reply_markup"]["inline_keyboard"][0]
    assert m["text"].startswith("PAPER · Buy anakin")
    assert btn[0] == {"text": "Buy on FOMO", "url": links.coin_url(MINT, "solana")}
    assert btn[0]["url"] == f"https://fomo.family/coin?address={MINT}&chainId=1399811149&r=savipww&source=share_link"
    assert [b.get("callback_data") for b in btn[1:]] == [f"bought:{MINT}", f"skip:{MINT}"]
    assert out["link"] == btn[0]["url"]
def test_report_link_roundtrip(c):
    import report
    assert report.last_link(c) is None
    report.save_link(c, "https://example.page/night"); assert report.last_link(c) == "https://example.page/night"
    d = report.build(c); assert d["footer"] == "New to FOMO? https://fomo.family/r/savipww"
