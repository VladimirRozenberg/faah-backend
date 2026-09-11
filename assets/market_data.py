"""Récupère les prix et les bougies avec yfinance."""

from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from assets.schemas import AssetSummary, Candle, CandleResponse
from models import Asset


ALLOWED_PERIOD_INTERVALS = {
    "1d": {"1m", "5m", "15m", "30m", "1h"},
    "5d": {"5m", "15m", "30m", "1h"},
    "1mo": {"30m", "1h", "1d"},
    "3mo": {"1h", "1d"},
    "6mo": {"1d"},
    "1y": {"1d", "1wk"},
}


class InvalidHistoryRequestError(ValueError):
    """La période et l'intervalle ne sont pas compatibles."""


class MarketDataUnavailableError(RuntimeError):
    """Yahoo Finance n'a retourné aucune donnée utilisable."""


def get_symbol_data(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Prend uniquement les données qui appartiennent au symbole."""

    # [IA-02] Partie technique avec l'aide de l'IA : pandas organise
    # parfois les colonnes sur deux niveaux, par exemple AAPL puis Close.
    # On sélectionne alors le tableau du symbole demandé.
    if not isinstance(data.columns, pd.MultiIndex):
        return data

    if symbol not in data.columns.get_level_values(0):
        return pd.DataFrame()

    return data[symbol]


def get_market_assets(database_assets: list[Asset]) -> list[AssetSummary]:
    """Retourne le prix des actifs présents dans PostgreSQL."""

    if not database_assets:
        return []

    try:
        # Un seul appel groupé pour tous les actifs, sur les cinq derniers
        # jours. Cela permet de comparer les deux dernières clôtures reçues.
        market_data = yf.download(
            [asset.ast_symbol for asset in database_assets],
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception as error:
        raise MarketDataUnavailableError(
            "Impossible de contacter Yahoo Finance."
        ) from error

    if market_data.empty:
        raise MarketDataUnavailableError(
            "Yahoo Finance n'a retourné aucun cours."
        )

    results = []
    retrieved_at = datetime.now(timezone.utc)

    for asset in database_assets:
        asset_data = get_symbol_data(market_data, asset.ast_symbol)

        if asset_data.empty or "Close" not in asset_data:
            continue

        # Convertir les valeurs en nombres et retirer les données manquantes.
        # iloc[-1] désigne la dernière ligne ; iloc[-2], l'avant-dernière.
        closes = pd.to_numeric(
            asset_data["Close"], errors="coerce"
        ).dropna()
        if closes.empty:
            continue

        current_price = float(closes.iloc[-1])
        previous_close = current_price
        if len(closes) >= 2:
            previous_close = float(closes.iloc[-2])

        change = current_price - previous_close
        change_percent = 0
        if previous_close != 0:
            change_percent = change / previous_close * 100

        volume = None
        if "Volume" in asset_data:
            volumes = pd.to_numeric(
                asset_data["Volume"], errors="coerce"
            ).dropna()
            if not volumes.empty:
                volume = int(volumes.iloc[-1])

        results.append(
            AssetSummary(
                symbol=asset.ast_symbol,
                name=asset.ast_name,
                type=asset.ast_type,
                exchange=asset.ast_exchange,
                currency=asset.ast_currency or "USD",
                last_price=round(current_price, 4),
                previous_close=round(previous_close, 4),
                change=round(change, 4),
                change_percent=round(change_percent, 4),
                volume=volume,
                retrieved_at=retrieved_at,
            )
        )

    if not results:
        raise MarketDataUnavailableError(
            "Yahoo Finance n'a retourné aucun cours."
        )

    return results


def get_market_asset(database_asset: Asset) -> AssetSummary:
    """Retourne le prix d'un seul actif."""

    return get_market_assets([database_asset])[0]


def get_candles(
    symbol: str,
    period: str = "1d",
    interval: str = "5m",
) -> CandleResponse:
    """Retourne les bougies utilisées par le graphique."""

    symbol = symbol.upper()
    allowed_intervals = ALLOWED_PERIOD_INTERVALS.get(period)

    if allowed_intervals is None or interval not in allowed_intervals:
        raise InvalidHistoryRequestError(
            f"La combinaison {period}/{interval} n'est pas autorisée."
        )

    try:
        history = yf.Ticker(symbol).history(
            period=period,
            interval=interval,
            auto_adjust=False,
        )
    except Exception as error:
        raise MarketDataUnavailableError(
            f"Impossible de récupérer l'historique de {symbol}."
        ) from error

    required_columns = ["Open", "High", "Low", "Close"]
    if history.empty or not set(required_columns).issubset(history.columns):
        raise MarketDataUnavailableError(
            f"Aucune bougie disponible pour {symbol}."
        )

    # Une bougie décrit l'ouverture, le plus haut, le plus bas et la clôture
    # pendant un intervalle. On ignore les lignes où l'un de ces prix manque.
    history = history.dropna(subset=required_columns)
    candles = []

    for timestamp, row in history.iterrows():
        raw_volume = row.get("Volume")
        volume = None
        if not pd.isna(raw_volume):
            volume = int(raw_volume)

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
            f"Aucune bougie disponible pour {symbol}."
        )

    return CandleResponse(
        symbol=symbol,
        period=period,
        interval=interval,
        count=len(candles),
        candles=candles,
        retrieved_at=datetime.now(timezone.utc),
    )
