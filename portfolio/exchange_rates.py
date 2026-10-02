"""Conversion vers USD avec les taux de référence Frankfurter."""

import asyncio
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx


@dataclass(frozen=True)
class UsdRate:
    # Facteur applicable au prix d'origine, y compris les éventuels centimes.
    factor: Decimal
    rate_date: date


_cache: dict[str, tuple[float, UsdRate]] = {}
_locks: dict[str, asyncio.Lock] = {}
_failures: dict[str, float] = {}


def normalize_currency(currency: str) -> tuple[str, Decimal]:
    """Yahoo peut donner un prix en pence, cents ou agorot."""
    if currency in ("GBp", "GBX"):
        return "GBP", Decimal("0.01")
    if currency in ("ZAc", "ZAC"):
        return "ZAR", Decimal("0.01")
    if currency == "ILA":
        return "ILS", Decimal("0.01")
    code = currency.strip().upper()
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise ValueError("The asset currency is unavailable or unsupported.")
    return code, Decimal("1")


def parse_rate(data: dict, currency: str) -> UsdRate:
    """Vérifier le sens, la valeur et la date avant d'utiliser un taux."""
    if (not isinstance(data, dict) or not isinstance(data.get("base"), str)
            or not isinstance(data.get("quote"), str) or not isinstance(data.get("date"), str)):
        raise ValueError("Invalid exchange rate response.")
    rate = Decimal(str(data["rate"]))
    rate_date = date.fromisoformat(data["date"])
    today = datetime.now(timezone.utc).date()
    if (data["base"].upper() != currency or data["quote"].upper() != "USD"
            or not rate.is_finite() or rate <= 0
            or not 0 <= (today - rate_date).days <= 7):
        raise ValueError("Invalid or outdated exchange rate.")
    return UsdRate(rate, rate_date)


async def get_usd_rate(currency: str) -> UsdRate:
    """Une requête par devise et par heure ; aucun appel pour USD."""
    code, scale = normalize_currency(currency)
    if code == "USD":
        return UsdRate(scale, datetime.now(timezone.utc).date())

    # Le verrou évite plusieurs requêtes identiques lors d'achats simultanés.
    async with _locks.setdefault(code, asyncio.Lock()):
        cached = _cache.get(code)
        if cached is not None and cached[0] > time.monotonic():
            rate = cached[1]
        else:
            if _failures.get(code, 0) > time.monotonic():
                raise ValueError(f"USD conversion unavailable for {code}. Please retry shortly.")
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    response = await client.get(
                        f"https://api.frankfurter.dev/v2/rate/{code.lower()}/usd"
                    )
                    response.raise_for_status()
                    rate = parse_rate(response.json(), code)
                _cache[code] = (time.monotonic() + 3600, rate)
                _failures.pop(code, None)
            except (httpx.HTTPError, ValueError, KeyError, TypeError, ArithmeticError) as error:
                # Une panne ne doit jamais provoquer un achat avec un taux inventé.
                _failures[code] = time.monotonic() + 60
                raise ValueError(f"USD conversion unavailable for {code}. Please retry shortly.") from error
        return UsdRate(rate.factor * scale, rate.rate_date)
