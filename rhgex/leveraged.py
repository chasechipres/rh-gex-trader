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
    "GMEU": ("GME", 2),    # T-REX 2X Long GME Daily Target
    "METU": ("META", 2),   # Direxion Daily META Bull 2X
    "FBL": ("META", 2),    # GraniteShares 2x Long META Daily
    "GGLL": ("GOOGL", 2),  # Direxion Daily GOOGL Bull 2X
    "AMZU": ("AMZN", 2),   # Direxion Daily AMZN Bull 2X
    "HOOX": ("HOOD", 2),   # Defiance Daily Target 2X Long HOOD
    "HOOG": ("HOOD", 2),   # Leverage Shares 2X Long HOOD Daily
    "OKLL": ("OKLO", 2),   # Defiance Daily Target 2x Long OKLO
    "SMCX": ("SMCI", 2),   # Defiance Daily Target 2X Long SMCI
    "SMCL": ("SMCI", 2),   # GraniteShares 2x Long SMCI Daily
    "MUU": ("MU", 2),      # Direxion Daily MU Bull 2X
    "SOFX": ("SOFI", 2),   # Defiance Daily Target 2X Long SOFI
    "ARMG": ("ARM", 2),    # Leverage Shares 2X Long ARM Daily
    "HIMZ": ("HIMS", 2),   # Defiance Daily Target 2X Long HIMS
    "DLLL": ("DELL", 2),   # GraniteShares 2x Long DELL Daily
    "ORCX": ("ORCL", 2),   # Defiance Daily Target 2X Long ORCL
    "ORCU": ("ORCL", 2),   # Direxion Daily ORCL Bull 2X
    "ASTX": ("ASTS", 2),   # Tradr 2X Long ASTS Daily
    "CIFU": ("CIFR", 2),   # T-REX 2X Long CIFR Daily Target
    "CRWU": ("CRWV", 2),   # T-REX 2X Long CRWV Daily Target
    "ONDL": ("ONDS", 2),   # Defiance Daily Target 2X Long ONDS
    # inverse: a bearish read on the stock without shorting (the account can't short)
    "NVD": ("NVDA", -2),   # GraniteShares 2x Short NVDA Daily
    "NVDQ": ("NVDA", -2),  # T-Rex 2X Inverse NVIDIA Daily Target
    "TSLQ": ("TSLA", -2),  # Tradr 2X Short TSLA Daily
    "TSLZ": ("TSLA", -2),  # T-Rex 2X Inverse Tesla Daily Target
    "MSTZ": ("MSTR", -2),  # T-Rex 2X Inverse MSTR Daily Target
    "NBIZ": ("NBIS", -2),  # Tradr 2X Short NBIS Daily
    "SMCZ": ("SMCI", -2),  # Defiance Daily Target 2X Short SMCI
    "NVDD": ("NVDA", -1),  # Direxion Daily NVDA Bear 1X
    "TSLS": ("TSLA", -1),  # Direxion Daily TSLA Bear 1X
    "TSMZ": ("TSM", -1),   # Direxion Daily TSM Bear 1X
    "AMDD": ("AMD", -1),   # Direxion Daily AMD Bear 1X
    "METD": ("META", -1),  # Direxion Daily META Bear 1X
    "GGLS": ("GOOGL", -1),  # Direxion Daily GOOGL Bear 1X
    "AMZD": ("AMZN", -1),  # Direxion Daily AMZN Bear 1X
    "MUD": ("MU", -1),     # Direxion Daily MU Bear 1X
}
MAX_LEVERAGE = 2           # funds above this (either way) are refused by preflight
MAX_SPREAD_OF_RISK = 0.05  # a fund's bid/ask spread, as a share of the distance from entry to its stop
MIN_DOLLAR_VOLUME = 5_000_000  # average daily dollar volume, so a stop-out doesn't move the price
MAX_OPEN = 2               # leveraged or inverse funds open at once
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
