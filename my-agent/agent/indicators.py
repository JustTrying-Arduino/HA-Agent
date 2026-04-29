"""Close-only technical indicators for the Degiro pipeline.

Pure stdlib. All inputs are plain `list[float]` of closing prices in
chronological order (oldest first). Degiro's price_history returns
close-only data, so open/high/low/volume are never used here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n or n <= 0:
        return None
    return sum(closes[-n:]) / n


def rsi14(closes: list[float], period: int = 14) -> float | None:
    """RSI Wilder over `period` closes. Needs period+1 points."""
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def slope(closes: list[float], n: int) -> float | None:
    """Linear regression slope over the last N points, normalized as %/step."""
    if len(closes) < n or n < 2:
        return None
    window = closes[-n:]
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(window) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, window))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0 or mean_y == 0:
        return None
    slope_raw = num / den
    return (slope_raw / mean_y) * 100.0


def breakout_20d(closes: list[float]) -> bool:
    if len(closes) < 21:
        return False
    return closes[-1] > max(closes[-21:-1])


def variation(closes: list[float], n: int) -> float | None:
    """% change between close now and close N steps ago."""
    if len(closes) <= n:
        return None
    base = closes[-(n + 1)]
    if base == 0:
        return None
    return ((closes[-1] / base) - 1.0) * 100.0


def drawdown_from_high(current: float | None, high: float | None) -> float | None:
    if current is None or not high:
        return None
    return ((current / high) - 1.0) * 100.0


@dataclass
class SupportLevel:
    price: float
    count: int


def support_levels(
    closes: list[float], *, tol: float = 0.02, min_count: int = 3
) -> list[SupportLevel]:
    """Crude close-only clustering: a level is a price where many closes land
    within ±tol of each other. Returns levels ordered by density (desc)."""
    if not closes:
        return []
    levels: list[list[float]] = []
    for c in closes:
        placed = False
        for bucket in levels:
            ref = bucket[0]
            if abs(c - ref) / ref <= tol:
                bucket.append(c)
                placed = True
                break
        if not placed:
            levels.append([c])
    dense = [
        SupportLevel(price=sum(b) / len(b), count=len(b))
        for b in levels
        if len(b) >= min_count
    ]
    dense.sort(key=lambda lv: lv.count, reverse=True)
    return dense


def distance_to_nearest_support(
    current: float, levels: list[SupportLevel]
) -> tuple[SupportLevel, float] | None:
    """Return (level, distance_pct) for the closest level below or at current."""
    if not levels or current == 0:
        return None
    below = [lv for lv in levels if lv.price <= current]
    if not below:
        return None
    nearest = min(below, key=lambda lv: current - lv.price)
    dist_pct = ((current / nearest.price) - 1.0) * 100.0
    return nearest, dist_pct


# ---------------------------------------------------------------------------
# Strategy evaluation
# ---------------------------------------------------------------------------


@dataclass
class StrategyVerdict:
    strategy: str
    signal: str  # "candidate", "reject", "neutral"
    score: int
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)


def _last(closes: list[float]) -> float | None:
    return closes[-1] if closes else None


REBOUND_RSI_GATE = 35.0
REBOUND_RECOVERY_3D_THRESHOLD = 4.0
REBOUND_BOUNCE_MIN = 0.3
REBOUND_BOUNCE_MAX = 2.0


def evaluate_rebound(
    closes: list[float],
    *,
    high_52w: float | None,
    drawdown_threshold: float = -20.0,
) -> StrategyVerdict:
    """Rebond après forte baisse: RSI ≤ 35 (gate strict), drawdown vs 52w
    high, proximité support, début de reprise mesurée. Filtre anti-rattrapage:
    si la reprise est déjà avancée (var_3d > +4%), bascule en `recovery`
    (ticket parti). Rejet `falling knife` si support cassé + RSI bas +
    SMA50 descendante."""
    verdict = StrategyVerdict(strategy="rebound", signal="neutral", score=0)
    if len(closes) < 30:
        verdict.reasons.append("not enough history (need ≥30 closes)")
        return verdict

    rsi = rsi14(closes)
    sma50 = sma(closes, 50)
    slope50 = slope(closes, 50) if len(closes) >= 50 else None
    dd = drawdown_from_high(_last(closes), high_52w)
    levels = support_levels(closes)
    last = closes[-1]
    sup = distance_to_nearest_support(last, levels)
    densest = levels[0] if levels else None
    support_broken = densest is not None and last < densest.price * 0.98
    var_1d = variation(closes, 1)
    var_3d = variation(closes, 3)

    verdict.metrics = {
        "rsi14": rsi,
        "sma50": sma50,
        "slope50_pct": slope50,
        "drawdown_52w_pct": dd,
        "close": last,
        "support_price": sup[0].price if sup else None,
        "support_distance_pct": sup[1] if sup else None,
        "densest_level": densest.price if densest else None,
        "var_1d_pct": var_1d,
        "var_3d_pct": var_3d,
    }

    falling_knife = (
        support_broken
        and rsi is not None
        and rsi < 30
        and slope50 is not None
        and slope50 < 0
    )
    if falling_knife:
        verdict.signal = "reject"
        verdict.reasons.append("falling knife: support broken + RSI low + SMA50 down")
        return verdict

    if rsi is None or rsi > REBOUND_RSI_GATE:
        rsi_str = f"{rsi:.1f}" if rsi is not None else "n/a"
        verdict.reasons.append(
            f"RSI14 not oversold ({rsi_str} > {REBOUND_RSI_GATE:.0f}) — not a rebound setup"
        )
        return verdict

    if var_3d is not None and var_3d > REBOUND_RECOVERY_3D_THRESHOLD:
        verdict.signal = "recovery"
        verdict.reasons.append(
            f"recovery already in progress (var_3d {var_3d:+.1f}% > "
            f"+{REBOUND_RECOVERY_3D_THRESHOLD:.0f}%) — ticket parti"
        )
        return verdict

    verdict.score += 1
    verdict.reasons.append(
        f"RSI14 oversold ({rsi:.1f}{' — extreme' if rsi < 20 else ''})"
    )
    if dd is not None and dd <= drawdown_threshold:
        verdict.score += 1
        verdict.reasons.append(f"drawdown vs 52w high {dd:+.1f}%")
    if sup is not None and 0 <= sup[1] <= 3.0:
        verdict.score += 1
        verdict.reasons.append(
            f"near support {sup[0].price:.2f} ({sup[1]:+.1f}%)"
        )

    if (
        var_1d is not None
        and REBOUND_BOUNCE_MIN <= var_1d <= REBOUND_BOUNCE_MAX
    ):
        verdict.score += 1
        verdict.reasons.append(
            f"early bounce ({var_1d:+.1f}% on last close — measured pace)"
        )
    elif var_1d is not None and var_1d > REBOUND_BOUNCE_MAX:
        verdict.reasons.append(
            f"bounce too stretched ({var_1d:+.1f}% on last close) — no point"
        )

    if verdict.score >= 3:
        verdict.signal = "candidate"
    return verdict


def evaluate_swing(closes: list[float]) -> StrategyVerdict:
    """Swing: MM50/MM200 bullish, pullback propre vers SMA50, reprise close-only,
    breakout close-only sur plus haut 20j."""
    verdict = StrategyVerdict(strategy="swing", signal="neutral", score=0)
    if len(closes) < 210:
        verdict.reasons.append("not enough history (need ≥210 closes for SMA200)")
        return verdict

    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)
    slope50 = slope(closes, 50)
    last = closes[-1]

    verdict.metrics = {
        "close": last,
        "sma50": sma50,
        "sma200": sma200,
        "slope50_pct": slope50,
        "breakout_20d": 1.0 if breakout_20d(closes) else 0.0,
    }

    trend_up = (
        sma50 is not None
        and sma200 is not None
        and last > sma200
        and sma50 > sma200
    )
    if trend_up:
        verdict.score += 1
        verdict.reasons.append(
            f"trend up: close {last:.2f} > SMA200 {sma200:.2f}, SMA50 > SMA200"
        )

    pullback = (
        trend_up
        and sma50 is not None
        and abs(last - sma50) / sma50 <= 0.03
        and slope50 is not None
        and slope50 > 0
    )
    if pullback:
        verdict.score += 1
        verdict.reasons.append(
            f"clean pullback near SMA50 ({(last - sma50) / sma50 * 100:+.1f}%)"
        )

    if len(closes) >= 2 and closes[-1] > closes[-2]:
        verdict.score += 1
        verdict.reasons.append("close-only recovery (close today > close yesterday)")

    if breakout_20d(closes):
        verdict.score += 1
        verdict.reasons.append("close-only breakout over 20d high")

    if not trend_up:
        # No point screening swing when trend is flat or bearish.
        return verdict

    if verdict.score >= 3:
        verdict.signal = "candidate"
    return verdict


def evaluate(
    strategy: str,
    closes: list[float],
    *,
    high_52w: float | None = None,
) -> StrategyVerdict:
    if strategy == "rebound":
        return evaluate_rebound(closes, high_52w=high_52w)
    if strategy == "swing":
        return evaluate_swing(closes)
    raise ValueError(f"Unknown strategy '{strategy}' (expected 'rebound' or 'swing')")
