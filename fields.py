"""Field paths mapped from raw samples in logs/raw/ (STEP 2, 2026-11-02).
A path of None = key not present in the samples; callers must treat the value as null.
Paths: tuple of keys; "[]" means iterate a list."""
MIGRATION = {  # PumpPortal subscribeMigration message
    "mint": ("mint",),
    "pool": None,        # "pool" key exists but holds a venue label ("pump-amm"/"raydium-cpmm"), not an address
    "pool_label": ("pool",),
    "signature": ("signature",),
    "creator": None,     # not in message
    "tx_type": ("txType",),
}
DEXSCREENER = {  # /tokens/v1/solana/{mint} -> list of pairs
    "dexId": ("dexId",), "pairAddress": ("pairAddress",), "priceUsd": ("priceUsd",),
    "liquidity_usd": ("liquidity", "usd"),   # absent on pumpfun curve pairs
    "marketCap": ("marketCap",),
    "volume_m5": ("volume", "m5"), "volume_h1": ("volume", "h1"), "volume_h24": ("volume", "h24"),
    "buys_m5": ("txns", "m5", "buys"), "sells_m5": ("txns", "m5", "sells"),
    "buys_h1": ("txns", "h1", "buys"), "sells_h1": ("txns", "h1", "sells"),
    "priceChange_m5": ("priceChange", "m5"), "priceChange_h1": ("priceChange", "h1"),
    "priceChange_h24": ("priceChange", "h24"), "pairCreatedAt": ("pairCreatedAt",),  # ms epoch
    "name": ("baseToken", "name"), "symbol": ("baseToken", "symbol"),
}
PUMPSWAP_DEX_ID = "pumpswap"
RUGCHECK_REPORT = {
    "creator": ("creator",), "creator_balance": ("creatorBalance",),
    "markets": ("markets",),                 # null when no market indexed
    "market_pool": ("pubkey",),              # per market; equals DexScreener pairAddress
    "market_type": ("marketType",),          # PumpSwap = "pump_fun_amm"
    "lp_locked_pct": ("lp", "lpLockedPct"),
    "lp_burned_pct": None,                   # no burn key anywhere in report
}
PUMPSWAP_MARKET_TYPE = "pump_fun_amm"
RUGCHECK_GRAPH = {  # list of networks
    "networks": (),
    "nodes": ("[]", "nodes"), "node_id": ("id",), "node_holdings": ("holdings",),
    "node_participant": ("participant",),
    "edges": ("[]", "links"), "edge_source": ("source",), "edge_target": ("target",),
    "holder_flag": None,  # no explicit flag; derive holdings > 0
}
RPC = {
    "mintAuthority": ("result", "value", "data", "parsed", "info", "mintAuthority"),
    "freezeAuthority": ("result", "value", "data", "parsed", "info", "freezeAuthority"),
    "supply": ("result", "value", "data", "parsed", "info", "supply"),
    "decimals": ("result", "value", "data", "parsed", "info", "decimals"),
    "token_program": ("result", "value", "owner"),
    "supply_amount": ("result", "value", "amount"),   # getTokenSupply
}
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

def get(obj, path):
    if path is None: return None
    for k in path:
        if isinstance(obj, dict): obj = obj.get(k)
        else: return None
    return obj
