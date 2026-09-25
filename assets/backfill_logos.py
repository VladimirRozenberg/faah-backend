"""Remplissage temporaire : python -m assets.backfill_logos --hours 3."""

import argparse
import asyncio
import logging
import math
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select, text

from assets.logos import fill_missing_logo
from db import AsyncSessionLocal, engine
from models import Asset

logger = logging.getLogger(__name__)


async def fill_one() -> tuple[str, str | None]:
    """Une transaction par actif : les logos déjà obtenus restent enregistrés."""
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Même verrou que le traitement automatique : ne pas télécharger
            # en parallèle avec lui. Aucun changement du code automatique.
            locked = await db.scalar(text("SELECT pg_try_advisory_xact_lock(20260923, 1)"))
            if not locked:
                return "wait", None

            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            # Les futures et les paires forex non reconnues sont exclus.
            supported = or_(
                Asset.ast_type.in_(["stock", "crypto"]),
                and_(Asset.ast_type == "forex", or_(
                    func.length(Asset.ast_symbol) == 6,
                    and_(func.length(Asset.ast_symbol) == 8, Asset.ast_symbol.endswith("=X")),
                )),
            )
            asset = await db.scalar(
                select(Asset)
                .where(
                    Asset.ast_logo_mime_type.is_(None),
                    supported,
                    or_(Asset.ast_logo_last_attempt_at.is_(None), Asset.ast_logo_last_attempt_at <= cutoff),
                )
                # Priorité aux actifs jamais essayés, puis aux tentatives anciennes.
                .order_by(Asset.ast_logo_last_attempt_at.asc().nulls_first(), Asset.ast_id)
                .limit(1)
            )
            if asset is None:
                return "done", None

            previous = asset.ast_logo_last_attempt_at
            # Réutilise les quotas, délais, contrôles d'image et stockage existants.
            await fill_missing_logo(db, asset)
            if asset.ast_logo_mime_type:
                return "saved", asset.ast_symbol
            if asset.ast_logo_last_attempt_at != previous:
                return "missing", asset.ast_symbol
            return "wait", None  # Quota atteint : réessayer plus tard.


async def run(hours: float) -> None:
    if not os.getenv("TWELVE_DATA_API_KEY", "").strip():
        raise SystemExit("TWELVE_DATA_API_KEY manque : aucun traitement lancé.")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + hours * 3600
    saved = 0
    attempted = 0
    logger.info("Remplissage lancé pour au maximum %.2f heure(s). Ctrl+C pour arrêter.", hours)
    try:
        while loop.time() < deadline:
            # Borne aussi l'attente d'une base qui ne répondrait plus.
            try:
                async with asyncio.timeout(min(60, deadline - loop.time())):
                    status, symbol = await fill_one()
            except TimeoutError:
                if loop.time() >= deadline:
                    logger.info("Durée maximale atteinte : arrêt du remplissage.")
                    break
                raise
            if status == "done":
                logger.info("Plus d'actif éligible. Les échecs récents attendent 24 h avant un nouvel essai.")
                break
            if status in ("saved", "missing"):
                attempted += 1
                saved += status == "saved"
                logger.info("%s : %s", symbol, "logo enregistré" if status == "saved" else "logo indisponible")
            else:
                logger.info("Quota ou traitement automatique occupé : pause de 60 secondes.")

            # Au plus 6 tentatives/minute ici ; le plafond partagé existant
            # reste de 7/minute et 750/24 h pour les appels de cette application.
            pause = 60 if status == "wait" else 10
            await asyncio.sleep(max(0, min(pause, deadline - loop.time())))
    finally:
        logger.info("Bilan : %s logo(s) enregistré(s), %s tentative(s).", saved, attempted)
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compléter les logos manquants sans changer le traitement automatique.")
    parser.add_argument("--hours", type=float, default=3, help="Durée maximale en heures (défaut : 3, maximum : 24).")
    args = parser.parse_args()
    if not math.isfinite(args.hours) or not 0 < args.hours <= 24:
        parser.error("--hours doit être supérieur à 0 et inférieur ou égal à 24.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run(args.hours))
    except KeyboardInterrupt:
        print("Arrêt demandé. Les logos déjà enregistrés sont conservés.")
    except Exception as error:
        # Ne pas afficher de chaîne de connexion ou de clé dans les logs.
        logger.error("Arrêt du script (%s). Vérifier le service et la base avant de relancer.", type(error).__name__)
        raise SystemExit(1)
