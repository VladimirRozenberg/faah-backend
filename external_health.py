"""Contrôles légers des fournisseurs, partagés entre les fenêtres Live."""

import asyncio
import math
import os
import time
from datetime import datetime, timezone


class CachedCheck:
    def __init__(self, seconds: int):
        self.seconds = seconds
        self.result = None
        self.expires = 0.0
        self.lock = asyncio.Lock()

    async def get(self, probe):
        # Un seul contrôle à la fois, même si plusieurs utilisateurs ouvrent Live.
        async with self.lock:
            if self.result is not None and time.monotonic() < self.expires:
                return self.result
            try:
                status, detail = await asyncio.wait_for(probe(), timeout=10)
            except TimeoutError:
                status, detail = "unavailable", "Provider did not respond in time."
            except Exception:
                # Ne jamais exposer une clé API ni le contenu brut d'une exception.
                status, detail = "unavailable", "Provider check failed."
            self.result = {
                "status": status,
                "detail": detail,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "cache_seconds": self.seconds,
            }
            self.expires = time.monotonic() + self.seconds
            return self.result


def _read_yahoo():
    import yfinance as yf

    # Cinq jours couvrent aussi les week-ends ; aucun achat et aucune écriture BDD.
    data = yf.Ticker("AAPL").history(period="5d", interval="1d", timeout=5)
    if data.empty or "Close" not in data:
        return False
    prices = data["Close"].dropna()
    return not prices.empty and math.isfinite(float(prices.iloc[-1])) and float(prices.iloc[-1]) > 0


async def check_yahoo():
    try:
        available = await asyncio.to_thread(_read_yahoo)
        return ("connected", "AAPL price received via yfinance.") if available else (
            "unavailable", "Yahoo returned no usable price for the test symbol."
        )
    except Exception as error:
        if type(error).__name__ == "YFRateLimitError":
            return "rate_limited", "Yahoo temporarily limited requests."
        raise


def twelve_result(code: int, data: dict):
    error_code = str(data.get("code", code))
    if code == 429 or error_code == "429":
        return "rate_limited", "Twelve Data request quota reached."
    if code in (401, 403) or error_code in ("401", "403"):
        return "authentication_failed", "API key or access permission refused."
    if code != 200 or data.get("status") == "error":
        return "unavailable", "Twelve Data returned an error."
    if not isinstance(data.get("current_usage"), (int, float)) or not isinstance(data.get("plan_limit"), (int, float)):
        return "unavailable", "Unexpected usage response from Twelve Data."
    if data["current_usage"] >= data["plan_limit"]:
        return "rate_limited", "Twelve Data minute quota reached."
    if isinstance(data.get("plan_daily_limit"), (int, float)) and isinstance(data.get("daily_usage"), (int, float)):
        if data["daily_usage"] >= data["plan_daily_limit"]:
            return "rate_limited", "Twelve Data daily quota reached."
    return "connected", "API access verified; logo availability depends on the asset."


async def check_twelve():
    api_key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
    if not api_key:
        return "not_configured", "API key is not configured on the server."
    import httpx

    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        response = await client.get("https://api.twelvedata.com/api_usage",
                                    headers={"Authorization": f"apikey {api_key}"})
        try:
            data = response.json()
        except ValueError:
            data = {}
        return twelve_result(response.status_code, data if isinstance(data, dict) else {})


# Cache par processus serveur : 5 min Yahoo, 30 min Twelve Data (contrôle payant en crédits).
yahoo_cache = CachedCheck(300)
twelve_cache = CachedCheck(1800)


async def get_external_health():
    yahoo, twelve = await asyncio.gather(yahoo_cache.get(check_yahoo), twelve_cache.get(check_twelve))
    return {"yfinance": yahoo, "twelve_data": twelve}
