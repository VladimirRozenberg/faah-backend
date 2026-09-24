"""Récupère un logo Twelve Data seulement quand un actif sans logo est rencontré."""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import Asset

logger = logging.getLogger(__name__)
MAX_LOGO_BYTES = 1024 * 1024  # 1 Mo maximum par image.


def get_logo_symbol(asset: Asset) -> str | None:
    """Adapte les symboles Yahoo au format Twelve Data."""
    if asset.ast_type == "stock":
        return asset.ast_symbol
    if asset.ast_type == "crypto":
        return asset.ast_symbol.replace("-", "/")
    if asset.ast_type == "forex":
        pair = asset.ast_symbol.removesuffix("=X")
        if len(pair) == 6:
            return pair[:3] + "/" + pair[3:]
    # L'endpoint logo ne prévoit pas les futures : on conserve les initiales.
    return None


async def download_logo(symbol: str, api_key: str) -> tuple[bytes, str] | None:
    """Télécharge une petite image"""
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        response = await client.get(
            "https://api.twelvedata.com/logo",
            params={"symbol": symbol},
            headers={"Authorization": f"apikey {api_key}"},
        )
        response.raise_for_status()
        data = response.json()
        url = data.get("url") or data.get("logo_base")
        if not url:
            return None

        # Télécharger uniquement depuis les hôtes officiels, sans redirection.
        address = urlparse(url)
        if (address.scheme != "https" or address.hostname not in
                {"api.twelvedata.com", "logo.twelvedata.com"}
                or address.username or address.password or address.port not in (None, 443)):
            return None

        async with client.stream("GET", url) as image:
            image.raise_for_status()
            mime = image.headers.get("content-type", "").split(";")[0].strip().lower()
            if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                return None
            content = bytearray()
            async for chunk in image.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_LOGO_BYTES:
                    return None
            if not content:
                return None
            return bytes(content), mime


async def fill_missing_logo(db: AsyncSession, asset: Asset) -> None:
    """Complète la fiche sans empêcher l'enregistrement si le fournisseur échoue."""
    api_key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
    symbol = get_logo_symbol(asset)
    if not api_key or not symbol or asset.ast_logo_mime_type:
        return

    now = datetime.now(timezone.utc)
    previous = asset.ast_logo_last_attempt_at
    if previous and now - previous < timedelta(hours=24):
        return

    # [IA-06] Partie technique avec l'aide de l'IA : le verrou évite que plusieurs
    # workers dépassent ensemble la limite. Pas d'attente si un autre l'utilise.
    # Il est libéré automatiquement au commit ou au rollback de la transaction.
    await db.flush()  # Inclure les tentatives des actifs précédents dans le comptage.
    with db.no_autoflush:
        locked = await db.scalar(text("SELECT pg_try_advisory_xact_lock(20260923, 1)"))
        if not locked:
            return
        for period, limit in [(timedelta(minutes=1), 7), (timedelta(hours=24), 750)]:
            attempts = await db.scalar(
                select(func.count()).select_from(Asset).where(
                    Asset.ast_logo_last_attempt_at >= now - period
                )
            )
            if attempts >= limit:
                return

    asset.ast_logo_last_attempt_at = now
    try:
        logo = await asyncio.wait_for(download_logo(symbol, api_key), timeout=12)
        if logo:
            asset.ast_logo, asset.ast_logo_mime_type = logo
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, TimeoutError):
        # Un message court suffit ; ne pas journaliser les détails HTTP sensibles.
        logger.warning("Logo indisponible pour %s ; les initiales restent affichées.", asset.ast_symbol)
