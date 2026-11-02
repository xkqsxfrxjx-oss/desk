"""THE ONLY place FOMO URLs are built. Every URL carries the referral r=savipww."""
from urllib.parse import quote
REF = "savipww"
SIGNUP_URL = f"https://fomo.family/r/{REF}"
# Verified token routes (fomo.family/tokens/{chain}/{address}); anything else -> SIGNUP_URL.
CHAINS = {"solana": "solana", "bnb": "bnb", "bsc": "bnb", "robinhood": "robinhood"}  # base: route not verified

def coin_url(mint: str, chain: str = "solana") -> str:
    slug = CHAINS.get((chain or "").lower())
    if not slug or not mint:
        return SIGNUP_URL
    return f"https://fomo.family/tokens/{slug}/{quote(mint, safe='')}?r={REF}"

def profile_url(handle: str) -> str:
    return f"https://fomo.family/profile/{quote(handle, safe='')}?source=share_link&r={REF}"
