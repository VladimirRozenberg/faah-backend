"""Accès aux données financières avec yfinance.

Ce module est volontairement séparé de FastAPI. Plus tard, il sera possible de
remplacer yfinance par un autre fournisseur sans modifier toutes les routes.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

import pandas as pd
import yfinance as yf

from assets.catalog import ALL_ASSETS
from assets.schemas import AssetSummary, Candle, CandleResponse


# On limite les combinaisons afin d'éviter les requêtes invalides ou énormes.
ALLOWED_PERIOD_INTERVALS: dict[str, set[str]] = {
    "1d": {"1m", "5m", "15m", "30m", "1h"},
    "5d": {"5m", "15m", "30m", "1h"},
    "1mo": {"30m", "1h", "1d"},
    "3mo": {"1h", "1d"},
    "6mo": {"1d"},
    "1y": {"1d", "1wk"},
}


class UnknownSymbolError(ValueError):
    """Le symbole demandé ne fait pas partie de notre catalogue."""


class InvalidHistoryRequestError(ValueError):
    """La période et l'intervalle demandés ne sont pas compatibles."""


class MarketDataUnavailableError(RuntimeError):
    """Yahoo Finance n'a retourné aucune donnée exploitable."""


@dataclass
class CacheEntry:
    created_at: float
    value: object


class MarketDataService:
    """Service yfinance avec un petit cache mémoire de 60 secondes."""

    def __init__(self, cache_seconds: int = 60) -> None:
        self.cache_seconds = cache_seconds
        self._cache: dict[str, CacheEntry] = {}
        self._cache_lock = Lock()

    def _read_cache(self, key: str) -> object | None:
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if monotonic() - entry.created_at >= self.cache_seconds:
                del self._cache[key]
                return None
            return entry.value

    def _write_cache(self, key: str, value: object) -> None:
        with self._cache_lock:
            self._cache[key] = CacheEntry(monotonic(), value)

    @staticmethod
    def _symbol_frame(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Extrait les colonnes d'un symbole d'un téléchargement groupé."""

        if isinstance(data.columns, pd.MultiIndex):
            try:
                return data[symbol]
            except KeyError:
                return pd.DataFrame()
        return data

    @staticmethod
    def _last_number(series: pd.Series) -> float | None:
        numbers = pd.to_numeric(series, errors="coerce").dropna()
        if numbers.empty:
            return None
        return float(numbers.iloc[-1])

    def get_assets(self) -> list[AssetSummary]:
        """Retourne le prix et la variation des actifs du catalogue."""

        cached = self._read_cache("assets")
        if cached is not None:
            return cached  # type: ignore[return-value]

        symbols = list(ALL_ASSETS)

        try:
            daily_data = yf.download(
                tickers=symbols,
                period="5d",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
            intraday_data = yf.download(
                tickers=symbols,
                period="1d",
                interval="5m",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
        except Exception as error:
            raise MarketDataUnavailableError(
                "Impossible de contacter Yahoo Finance pour le moment."
            ) from error

        if daily_data.empty:
            raise MarketDataUnavailableError("Yahoo Finance n'a retourné aucun cours.")

        retrieved_at = datetime.now(timezone.utc)
        assets: list[AssetSummary] = []

        for symbol, metadata in ALL_ASSETS.items():
            daily = self._symbol_frame(daily_data, symbol)
            intraday = self._symbol_frame(intraday_data, symbol)

            if daily.empty or "Close" not in daily:
                continue

            daily_closes = pd.to_numeric(daily["Close"], errors="coerce").dropna()
            if daily_closes.empty:
                continue

            daily_last = float(daily_closes.iloc[-1])
            previous_close = (
                float(daily_closes.iloc[-2]) if len(daily_closes) >= 2 else daily_last
            )

            intraday_last = None
            daily_volume = (
                self._last_number(daily["Volume"]) if "Volume" in daily else None
            )
            volume = int(daily_volume) if daily_volume is not None else None
            if not intraday.empty:
                if "Close" in intraday:
                    intraday_last = self._last_number(intraday["Close"])

            last_price = intraday_last if intraday_last is not None else daily_last
            change = last_price - previous_close
            change_percent = (
                (change / previous_close) * 100 if previous_close != 0 else 0.0
            )

            assets.append(
                AssetSummary(
                    symbol=symbol,
                    name=metadata["name"],
                    type=metadata["type"],
                    exchange=metadata.get("exchange"),
                    currency=metadata.get("quote", "USD"),
                    last_price=round(last_price, 4),
                    previous_close=round(previous_close, 4),
                    change=round(change, 4),
                    change_percent=round(change_percent, 4),
                    volume=volume,
                    retrieved_at=retrieved_at,
                )
            )

        if not assets:
            raise MarketDataUnavailableError(
                "Aucun actif n'a retourné un cours exploitable."
            )

        self._write_cache("assets", assets)
        return assets

    def get_asset(self, symbol: str) -> AssetSummary:
        normalized_symbol = symbol.upper()
        if normalized_symbol not in ALL_ASSETS:
            raise UnknownSymbolError(normalized_symbol)

        asset = next(
            (item for item in self.get_assets() if item.symbol == normalized_symbol),
            None,
        )
        if asset is None:
            raise MarketDataUnavailableError(
                f"Aucun cours n'est actuellement disponible pour {normalized_symbol}."
            )
        return asset

    def get_candles(
        self, symbol: str, period: str = "1d", interval: str = "5m"
    ) -> CandleResponse:
        normalized_symbol = symbol.upper()
        if normalized_symbol not in ALL_ASSETS:
            raise UnknownSymbolError(normalized_symbol)

        allowed_intervals = ALLOWED_PERIOD_INTERVALS.get(period)
        if allowed_intervals is None or interval not in allowed_intervals:
            raise InvalidHistoryRequestError(
                f"La combinaison period={period} et interval={interval} n'est pas autorisée."
            )

        cache_key = f"candles:{normalized_symbol}:{period}:{interval}"
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        try:
            history = yf.Ticker(normalized_symbol).history(
                period=period,
                interval=interval,
                auto_adjust=False,
            )
        except Exception as error:
            raise MarketDataUnavailableError(
                f"Impossible de récupérer l'historique de {normalized_symbol}."
            ) from error

        if history.empty:
            raise MarketDataUnavailableError(
                f"Yahoo Finance n'a retourné aucun historique pour {normalized_symbol}."
            )

        candles: list[Candle] = []
        for timestamp, row in history.iterrows():
            required_values = [row.get("Open"), row.get("High"), row.get("Low"), row.get("Close")]
            if any(pd.isna(value) for value in required_values):
                continue

            raw_volume = row.get("Volume")
            volume = None if pd.isna(raw_volume) else int(raw_volume)
            candles.append(
                Candle(
                    timestamp=timestamp.to_pydatetime(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=volume,
                )
            )

        if not candles:
            raise MarketDataUnavailableError(
                f"L'historique de {normalized_symbol} ne contient aucune bougie valide."
            )

        response = CandleResponse(
            symbol=normalized_symbol,
            period=period,
            interval=interval,
            count=len(candles),
            candles=candles,
            retrieved_at=datetime.now(timezone.utc),
        )
        self._write_cache(cache_key, response)
        return response


market_data_service = MarketDataService()
