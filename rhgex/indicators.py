def ema(values: list[float], period: int) -> list[float]:
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], period: int = 14) -> float:
    gains, losses = 0.0, 0.0
    for prev, cur in zip(closes[-period - 1 : -1], closes[-period:]):
        change = cur - prev
        gains += max(change, 0)
        losses += max(-change, 0)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - 100 / (1 + rs)


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    trs = [
        max(h - l, abs(h - pc), abs(l - pc))
        for h, l, pc in zip(highs[-period:], lows[-period:], closes[-period - 1 : -1])
    ]
    return sum(trs) / len(trs)
