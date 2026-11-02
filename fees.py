"""FOMO fee model on Solana (STEP 11), per side. Gas = 0 (FOMO pays)."""
def side_fee(ticket_usd: float, ref_discount: float = 0.10) -> float:
    t = abs(ticket_usd)
    if t <= 0: return 0.0
    if t <= 47.50: fee = 0.02 * t
    elif t <= 190: fee = 0.95
    else: fee = 0.005 * t
    return round(fee * (1 - ref_discount), 6)

def round_trip(entry_usd: float, exit_usd: float, ref_discount: float = 0.10) -> float:
    return round(side_fee(entry_usd, ref_discount) + side_fee(exit_usd, ref_discount), 6)
