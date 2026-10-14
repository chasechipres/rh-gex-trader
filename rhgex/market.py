"""Price, technical and fundamental snapshot for a ticker (Yahoo Finance via yfinance)."""

import logging

import yfinance as yf

from .indicators import atr, ema, rsi

# yfinance logs HTTP errors (e.g. no fundamentals for ETFs) to stderr; we report gaps in the JSON instead.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Index symbols as Yahoo names them.
YAHOO = {"SPX": "^SPX", "XSP": "^XSP", "NDX": "^NDX", "RUT": "^RUT", "VIX": "^VIX"}

FUNDAMENTALS = (
    "sector", "industry", "marketCap", "trailingPE", "forwardPE", "pegRatio", "priceToSalesTrailing12Months",
    "revenueGrowth", "earningsGrowth", "grossMargins", "operatingMargins", "profitMargins", "freeCashflow",
    "totalCash", "totalDebt", "sharesOutstanding", "shortPercentOfFloat", "beta",
    "recommendationMean", "targetMeanPrice", "numberOfAnalystOpinions",
)


def yahoo_symbol(symbol: str) -> str:
    return YAHOO.get(symbol.upper(), symbol.upper())


def _pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 2)


def technicals(symbol: str) -> dict:
    h = yf.Ticker(yahoo_symbol(symbol)).history(period="1y", auto_adjust=True)
    if len(h) < 60:
        raise ValueError(f"not enough price history for {symbol}")
    closes, highs, lows, vols = (h[c].tolist() for c in ("Close", "High", "Low", "Volume"))
    px = closes[-1]
    e20, e50, e200 = ema(closes, 20)[-1], ema(closes, 50)[-1], ema(closes, 200)[-1]
    avg_vol20 = sum(vols[-21:-1]) / 20 or 1
    return {
        "price": round(px, 2),
        "as_of": h.index[-1].isoformat(),
        "ema20": round(e20, 2), "ema50": round(e50, 2), "ema200": round(e200, 2),
        "trend": "up" if px > e20 > e50 else "down" if px < e20 < e50 else "mixed",
        "above_ema200": px > e200,
        "rsi14": round(rsi(closes), 1),
        "atr14": round(atr(highs, lows, closes), 2),
        "atr_pct": round(atr(highs, lows, closes) / px * 100, 2),
        "volume_ratio": round(vols[-1] / avg_vol20, 2),
        "high_20d": round(max(highs[-20:]), 2), "low_20d": round(min(lows[-20:]), 2),
        "high_52w": round(max(highs), 2), "low_52w": round(min(lows), 2),
        "pct_from_52w_high": _pct(px, max(highs)),
        "return_1m_pct": _pct(px, closes[-22]), "return_3m_pct": _pct(px, closes[-64]),
        "recent_candles": [
            {"date": d.date().isoformat(), "o": round(r.Open, 2), "h": round(r.High, 2),
             "l": round(r.Low, 2), "c": round(r.Close, 2), "v": int(r.Volume)}
            for d, r in h.tail(15).iterrows()
        ],
    }


def next_earnings(symbol: str):
    """The next earnings date (a date), or None when Yahoo has none or the lookup fails."""
    try:
        dates = (yf.Ticker(yahoo_symbol(symbol)).calendar or {}).get("Earnings Date") or []
        return min(dates) if dates else None
    except Exception:
        return None


def fundamentals(symbol: str) -> dict:
    t = yf.Ticker(yahoo_symbol(symbol))
    try:
        info = t.info
    except Exception as e:  # Yahoo's quoteSummary endpoint is flaky; technicals still stand alone
        return {"error": f"fundamentals unavailable: {e}"}
    out = {k: info.get(k) for k in FUNDAMENTALS if info.get(k) is not None}
    if not out:
        out["error"] = f"no fundamentals for {symbol} (ETF/index or missing data)"
    try:
        dates = (t.calendar or {}).get("Earnings Date") or []
        out["next_earnings"] = [d.isoformat() for d in dates]
    except Exception:
        pass
    return out
