"""Shared HTTP clients: DexScreener (batched, rate-limited), Solana RPC, RugCheck. Raw keys via fields.py."""
import asyncio, time, httpx
from collections import deque
import fields
from fields import get as fget
from solders.pubkey import Pubkey
DEX = "https://api.dexscreener.com/tokens/v1/solana/"
RUG = "https://api.rugcheck.xyz/v1/tokens/"
PUMP_PROGRAM = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
_client = None
def client():
    global _client
    if _client is None: _client = httpx.AsyncClient(timeout=20, headers={"User-Agent": "desk/1"})
    return _client

class RateLimited(Exception): pass
class SourceError(Exception): pass

class Limiter:
    def __init__(self, per_min): self.per_min, self.t = per_min, deque()
    async def wait(self):
        while True:
            now = time.monotonic()
            while self.t and now - self.t[0] > 60: self.t.popleft()
            if len(self.t) < self.per_min: self.t.append(now); return
            await asyncio.sleep(60 - (now - self.t[0]) + 0.05)
dex_limiter = Limiter(250)

def pick_pair(pairs):
    """PumpSwap pair with most liquidity, else None."""
    ps = [p for p in pairs if fget(p, fields.DEXSCREENER["dexId"]) == fields.PUMPSWAP_DEX_ID]
    return max(ps, key=lambda p: fget(p, fields.DEXSCREENER["liquidity_usd"]) or 0) if ps else None

def norm(pair):
    """Flatten a DexScreener pair through fields.py. Missing keys stay None."""
    if pair is None: return None
    d = {k: fget(pair, p) for k, p in fields.DEXSCREENER.items()}
    if d["priceUsd"] is not None: d["priceUsd"] = float(d["priceUsd"])
    return d

async def dex_batch(mints):
    """{mint: normalized pumpswap pair or None}. Chunks of 30. Raises RateLimited on 429."""
    out = {m: None for m in mints}
    mints = list(mints)
    for i in range(0, len(mints), 30):
        chunk = mints[i:i + 30]
        await dex_limiter.wait()
        r = await client().get(DEX + ",".join(chunk))
        if r.status_code == 429: raise RateLimited()
        if r.status_code != 200: raise SourceError(f"dexscreener {r.status_code}")
        by = {}
        for p in r.json() or []:
            by.setdefault(fget(p, ("baseToken", "address")), []).append(p)
        for m in chunk: out[m] = norm(pick_pair(by.get(m, [])))
    return out

async def rpc(url, method, params, timeout=30):
    r = await client().post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout)
    if r.status_code == 429: raise RateLimited(method)
    j = r.json()
    if "error" in j: raise SourceError(f"{method}: {j['error'].get('message')}")
    return j["result"]

async def token_accounts(url, mint):
    """All token accounts of mint on Token + Token-2022 (jsonParsed). Layer 4, 8, holders, dev balance."""
    a = await rpc(url, "getProgramAccounts", [fields.TOKEN_PROGRAM, {"encoding": "jsonParsed",
        "filters": [{"dataSize": 165}, {"memcmp": {"offset": 0, "bytes": mint}}]}], timeout=60)
    b = await rpc(url, "getProgramAccounts", [fields.TOKEN_2022_PROGRAM, {"encoding": "jsonParsed",
        "filters": [{"memcmp": {"offset": 0, "bytes": mint}}]}], timeout=60)
    out = []
    for x in a + b:
        i = x["account"]["data"]["parsed"]["info"]
        out.append({"pubkey": x["pubkey"], "owner": i.get("owner"), "amount": int(i["tokenAmount"]["amount"]),
                    "delegate": i.get("delegate")})
    return out

def bonding_curve(mint):
    return str(Pubkey.find_program_address([b"bonding-curve", bytes(Pubkey.from_string(mint))], PUMP_PROGRAM)[0])

def top10_pct(accounts, supply, mint, pool):
    """Sum of the 10 biggest owners, pool and bonding curve excluded, as % of supply."""
    if not supply: return None
    skip = {pool, bonding_curve(mint)}
    per = {}
    for a in accounts:
        if a["owner"] in skip or a["amount"] <= 0: continue
        per[a["owner"]] = per.get(a["owner"], 0) + a["amount"]
    return round(100 * sum(sorted(per.values(), reverse=True)[:10]) / supply, 2)

def owner_balance(accounts, owner):
    return sum(a["amount"] for a in accounts if a["owner"] == owner)

async def mint_info(url, mint):
    v = await rpc(url, "getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    wrap = {"result": v}
    if v is None or v.get("value") is None: raise SourceError("mint account not found")
    return {k: fget(wrap, fields.RPC[k]) for k in ("mintAuthority", "freezeAuthority", "supply", "decimals", "token_program")}

async def rug_report(mint):
    r = await client().get(RUG + mint + "/report")
    if r.status_code != 200: raise SourceError(f"rugcheck report {r.status_code}")
    return r.json()

async def rug_graph(mint):
    r = await client().get(RUG + mint + "/insiders/graph")
    if r.status_code != 200: raise SourceError(f"rugcheck graph {r.status_code}")
    return r.json()
