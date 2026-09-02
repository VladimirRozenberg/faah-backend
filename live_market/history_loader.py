"""Téléchargement d'un historique récent avec yfinance."""

from datetime import timezone

import pandas as pd
import yfinance as yf

from asset_catalog import ALL_ASSETS
from live_market.candle_repository import save_candles
from live_market.config import TIMEFRAME
from live_market.market_schemas import LiveCandle


def download_recent_history() -> list[LiveCandle]:
    """Télécharge les bougies récentes des actifs du catalogue."""

    candles = []

    for symbol in ALL_ASSETS:
        history = yf.Ticker(symbol).history(
            period="1d",
            interval=TIMEFRAME,
            auto_adjust=False,
        )

        for timestamp, row in history.iterrows():
            prices = [row["Open"], row["High"], row["Low"], row["Close"]]

            if any(pd.isna(price) for price in prices):
                continue

            candle_time = timestamp.to_pydatetime()

            if candle_time.tzinfo is None:
                candle_time = candle_time.replace(tzinfo=timezone.utc)
            else:
                candle_time = candle_time.astimezone(timezone.utc)

            volume = 0 if pd.isna(row["Volume"]) else int(row["Volume"])

            candles.append(
                LiveCandle(
                    symbol=symbol,
                    timeframe=TIMEFRAME,
                    timestamp=candle_time,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=volume,
                )
            )

    return candles


async def backfill_recent_history() -> int:
    """Télécharge l'historique puis l'enregistre dans PostgreSQL."""

    candles = download_recent_history()
    return await save_candles(candles)
