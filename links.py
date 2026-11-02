"""THE ONLY place FOMO URLs are built (STEP 6). Every URL carries r=savipww."""
from logs_util import logger
log = logger("links")
CHAIN_ID = {"solana": 1399811149, "robinhood": 4663, "base": 8453, "bnb": 56}
SIGNUP_URL = "https://fomo.family/r/savipww"

def coin_url(address, chain="solana"):
    if chain not in CHAIN_ID:
        log.info(f"coin_url: unknown chain {chain!r} for {address}, returning SIGNUP_URL")
        return SIGNUP_URL
    return f"https://fomo.family/coin?address={address}&chainId={CHAIN_ID[chain]}&r=savipww&source=share_link"

def profile_url(handle):
    h = handle.lstrip("@")
    return f"https://fomo.family/profile/{h}?source=share_link&r=savipww"
