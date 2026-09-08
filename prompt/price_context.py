"""Compact Yahoo Finance context for future LLM analysis prompts."""

import asyncio
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf
from pydantic import BaseModel


class PriceContextUnavailableError(RuntimeError):
    """Yahoo Finance did not return enough usable market information."""


class CandleContext(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
    is_complete: bool


class PriceContext(BaseModel):
    symbol: str
    name: str | None = None
    asset_type: str | None = None
    exchange: str | None = None
    currency: str | None = None
    exchange_timezone: str | None = None
    market_status: str
    yahoo_market_state: str | None = None
    current_price: float
    price_timestamp: datetime | None = None
    quote_age_seconds: int | None = None
    is_stale: bool | None = None
    previous_close: float | None = None
    session_open: float | None = None
    change_from_previous_close: float | None = None
    change_from_previous_close_pct: float | None = None
    change_from_session_open: float | None = None
    change_from_session_open_pct: float | None = None
    last_completed_candle: CandleContext | None = None
    current_session_candle: CandleContext | None = None
    generated_at: datetime
    source: str = "Yahoo Finance via yfinance"


MARKET_STATES = {
    "REGULAR": "open",
    "PRE": "pre_market",
    "POST": "after_hours",
    "POSTPOST": "after_hours",
    "PREPRE": "pre_market",
    "CLOSED": "closed",
}


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def _timestamp(value: object) -> datetime | None:
    try:
        timestamp = datetime.fromtimestamp(float(value), timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    return timestamp


def _volume(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _completed_candle(
    history: pd.DataFrame,
    market_status: str,
) -> CandleContext | None:
    if history.empty:
        return None

    valid = history.dropna(subset=["Open", "High", "Low", "Close"])
    if valid.empty:
        return None

    position = -2 if market_status == "open" and len(valid) >= 2 else -1
    row = valid.iloc[position]
    index = valid.index[position]

    return CandleContext(
        timestamp=index.to_pydatetime(),
        open=float(row["Open"]),
        high=float(row["High"]),
        low=float(row["Low"]),
        close=float(row["Close"]),
        volume=_volume(row.get("Volume")),
        is_complete=True,
    )


def _current_session_candle(
    history: pd.DataFrame,
    market_status: str,
) -> CandleContext | None:
    if market_status != "open" or history.empty:
        return None

    valid = history.dropna(subset=["Open", "High", "Low", "Close"])
    if valid.empty:
        return None

    return CandleContext(
        timestamp=valid.index[-1].to_pydatetime(),
        open=float(valid["Open"].iloc[0]),
        high=float(valid["High"].max()),
        low=float(valid["Low"].min()),
        close=float(valid["Close"].iloc[-1]),
        volume=_volume(valid["Volume"].sum()) if "Volume" in valid else None,
        is_complete=False,
    )


def _change(current: float, reference: float | None) -> tuple[float | None, float | None]:
    if reference is None:
        return None, None

    absolute = current - reference
    percentage = absolute / reference * 100 if reference else None
    return round(absolute, 4), round(percentage, 4) if percentage is not None else None


def build_price_context(symbol: str) -> PriceContext:
    """Synchronously retrieve and calculate context for one Yahoo symbol."""

    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("Asset symbol cannot be empty")

    ticker = yf.Ticker(normalized_symbol)

    try:
        information = ticker.get_info()
        daily_history = ticker.history(
            period="5d",
            interval="1d",
            auto_adjust=False,
        )
        intraday_history = ticker.history(
            period="1d",
            interval="5m",
            auto_adjust=False,
        )
    except Exception as error:
        raise PriceContextUnavailableError(
            f"Unable to retrieve Yahoo data for {normalized_symbol}"
        ) from error

    information = information if isinstance(information, dict) else {}
    raw_market_state = information.get("marketState")
    normalized_state = str(raw_market_state).upper() if raw_market_state else None
    market_status = MARKET_STATES.get(normalized_state, "unknown")

    completed_candle = _completed_candle(daily_history, market_status)
    current_candle = _current_session_candle(intraday_history, market_status)

    current_price = _number(information.get("regularMarketPrice"))
    if current_candle is not None:
        current_price = current_candle.close
    elif current_price is None and completed_candle is not None:
        current_price = completed_candle.close

    if current_price is None:
        raise PriceContextUnavailableError(
            f"Yahoo Finance returned no usable price for {normalized_symbol}"
        )

    previous_close = _number(information.get("regularMarketPreviousClose"))
    session_open = (
        _number(information.get("regularMarketOpen"))
        if market_status == "open"
        else None
    )
    if session_open is None and current_candle is not None:
        session_open = current_candle.open

    change_close, change_close_pct = _change(current_price, previous_close)
    change_open, change_open_pct = _change(current_price, session_open)

    price_timestamp = _timestamp(information.get("regularMarketTime"))
    generated_at = datetime.now(timezone.utc)
    quote_age_seconds = None
    is_stale = None
    if price_timestamp is not None:
        quote_age_seconds = max(
            0,
            int((generated_at - price_timestamp).total_seconds()),
        )
        if market_status == "open":
            is_stale = quote_age_seconds > 300

    return PriceContext(
        symbol=str(information.get("symbol") or normalized_symbol).upper(),
        name=information.get("longName") or information.get("shortName"),
        asset_type=information.get("quoteType"),
        exchange=information.get("exchange"),
        currency=information.get("currency"),
        exchange_timezone=information.get("exchangeTimezoneName"),
        market_status=market_status,
        yahoo_market_state=normalized_state,
        current_price=round(current_price, 4),
        price_timestamp=price_timestamp,
        quote_age_seconds=quote_age_seconds,
        is_stale=is_stale,
        previous_close=round(previous_close, 4) if previous_close is not None else None,
        session_open=round(session_open, 4) if session_open is not None else None,
        change_from_previous_close=change_close,
        change_from_previous_close_pct=change_close_pct,
        change_from_session_open=change_open,
        change_from_session_open_pct=change_open_pct,
        last_completed_candle=completed_candle,
        current_session_candle=current_candle,
        generated_at=generated_at,
    )


async def get_price_context(symbol: str) -> PriceContext:
    """Run blocking yfinance calls without blocking FastAPI's event loop."""

    return await asyncio.to_thread(build_price_context, symbol)
