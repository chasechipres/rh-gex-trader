"""Single-stock leveraged ETFs: which stock each fund tracks, and translating the stock's levels to the fund.

Plans for a fund keep their stop and target on the UNDERLYING (his levels are on the stock); the exit check
quotes the underlying, and the resting stop on the fund is placed at fund_level(). Only funds listed here are
treated as leveraged: add one only after checking its prospectus name (issuer, "2x Long <TICKER> Daily").
"""

FUNDS = {  # fund -> (underlying, daily leverage)
    "NVDL": ("NVDA", 2),   # GraniteShares 2x Long NVDA Daily
    "TSLL": ("TSLA", 2),   # Direxion Daily TSLA Bull 2X
    "MSTU": ("MSTR", 2),   # T-Rex 2X Long MSTR Daily Target
    "TSMX": ("TSM", 2),    # Direxion Daily TSM Bull 2X
    "NBIL": ("NBIS", 2),   # GraniteShares 2x Long NBIS Daily
    "CRWG": ("CRWV", 2),   # Leverage Shares 2X Long CRWV Daily
    "AMDL": ("AMD", 2),    # GraniteShares 2x Long AMD Daily
    # inverse: a bearish read on the stock without shorting (the account can't short)
    "NVD": ("NVDA", -2),   # GraniteShares 2x Short NVDA Daily
    "TSLQ": ("TSLA", -2),  # Tradr 2X Short TSLA Daily
    "TSLZ": ("TSLA", -2),  # T-Rex 2X Inverse Tesla Daily Target
    "MSTZ": ("MSTR", -2),  # T-Rex 2X Inverse MSTR Daily Target
    "NBIZ": ("NBIS", -2),  # Tradr 2X Short NBIS Daily
}
MAX_LEVERAGE = 2           # funds above this (either way) are refused by preflight
TIME_STOP_DAYS = 5         # trading days a leveraged fund may sit without reaching 1R (daily reset decays it)


def underlying(symbol: str) -> tuple[str, int] | None:
    return FUNDS.get(symbol.upper())


def funds_for(stock: str) -> list[str]:
    return sorted(f for f, (u, _) in FUNDS.items() if u == stock.upper())


def fund_level(fund_price: float, stock_price: float, stock_level: float, leverage: int) -> float:
    """The fund's price when the stock moves from stock_price to stock_level, at the fund's daily leverage
    (negative for an inverse fund, whose price falls as the stock rises).
    Exact within a day; over several days the daily reset makes it approximate, so re-translate each check."""
    return round(fund_price * (1 + leverage * (stock_level / stock_price - 1)), 2)
