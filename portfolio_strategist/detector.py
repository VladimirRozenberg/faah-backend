"""Deterministic price-movement detection for the opportunity service."""

from datetime import datetime, timezone

from live_market.market_schemas import LiveQuote
from portfolio_strategist.schemas import PriceMovement


def detect_price_movement(
    previous: LiveQuote | None,
    current: LiveQuote,
    *,
    threshold_pct: float = 2.0,
    max_window_seconds: int = 15 * 60,
) -> PriceMovement | None:
    """Return a material movement only for a newer, reasonably close quote."""

    if previous is None or previous.price <= 0 or current.price <= 0:
        return None
    if current.symbol.upper() != previous.symbol.upper():
        return None

    previous_at = previous.timestamp.astimezone(timezone.utc)
    current_at = current.timestamp.astimezone(timezone.utc)
    window_seconds = int((current_at - previous_at).total_seconds())
    if window_seconds <= 0 or window_seconds > max_window_seconds:
        return None

    change_pct = (current.price - previous.price) / previous.price * 100
    if abs(change_pct) < threshold_pct:
        return None

    return PriceMovement(
        symbol=current.symbol.upper(),
        event_type="price_rise" if change_pct > 0 else "price_drop",
        price_before=previous.price,
        price_after=current.price,
        change_pct=round(change_pct, 4),
        window_seconds=window_seconds,
        detected_at=current_at,
    )


def risk_is_compatible(portfolio_risk: str | None, analysis_risk: str | None) -> bool:
    """Conservatively compare the portfolio and analysis risk labels."""

    levels = {"low": 1, "medium": 2, "high": 3}
    allowed = levels.get((portfolio_risk or "medium").lower(), 2)
    observed = levels.get((analysis_risk or "high").lower(), 3)
    return observed <= allowed
