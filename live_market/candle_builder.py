"""Construit une bougie d'une minute avec les nouveaux prix."""

from live_market.config import TIMEFRAME
from live_market.market_schemas import CandleState, LiveCandle, LiveQuote


def public_candle(state: CandleState) -> LiveCandle:
    """Retire l'information interne avant l'envoi à Avalonia."""

    return LiveCandle(
        symbol=state.symbol,
        timeframe=state.timeframe,
        timestamp=state.timestamp,
        open=state.open,
        high=state.high,
        low=state.low,
        close=state.close,
        volume=state.volume,
    )


def update_candle(
    current: CandleState | None,
    quote: LiveQuote,
) -> tuple[CandleState, LiveCandle | None]:
    """Met à jour la bougie actuelle avec un nouveau prix."""

    minute = quote.timestamp.replace(second=0, microsecond=0)

    added_volume = 0
    if current is not None:
        old_volume = current.last_day_volume
        new_volume = quote.day_volume

        if old_volume is not None and new_volume is not None:
            if new_volume >= old_volume:
                added_volume = new_volume - old_volume

    # La première bougie ou le début d'une nouvelle minute.
    if current is None or minute > current.timestamp:
        finished = public_candle(current) if current is not None else None

        new_candle = CandleState(
            symbol=quote.symbol,
            timeframe=TIMEFRAME,
            timestamp=minute,
            open=quote.price,
            high=quote.price,
            low=quote.price,
            close=quote.price,
            volume=added_volume,
            last_day_volume=quote.day_volume,
        )

        return new_candle, finished

    # Le prix appartient encore à la même minute.
    current.high = max(current.high, quote.price)
    current.low = min(current.low, quote.price)
    current.close = quote.price
    current.volume = current.volume + added_volume
    current.last_day_volume = quote.day_volume

    return current, None
