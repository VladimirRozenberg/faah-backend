"""Vérifie les symboles Yahoo et enregistre les actifs dans PostgreSQL."""

import asyncio
from datetime import datetime, timezone

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assets.schemas import DetectedAsset
from models import (
    Asset,
    ClassificationAsset,
    Crypto,
    Forex,
    Future,
    Stock,
)


# Yahoo utilise ses propres noms de types. FAAH utilise des noms plus simples.
YAHOO_TYPES = {
    "EQUITY": "stock",
    "CRYPTOCURRENCY": "crypto",
    "CURRENCY": "forex",
    "FUTURE": "future",
}


def get_yahoo_information(symbol: str) -> dict | None:
    """Vérifie un symbole et garde seulement les données utiles."""

    try:
        information = yf.Ticker(symbol).get_info()
    except Exception:
        return None

    if not isinstance(information, dict):
        return None

    raw_yahoo_type = information.get("quoteType")
    yahoo_type = str(raw_yahoo_type).upper() if raw_yahoo_type else None
    asset_type = YAHOO_TYPES.get(yahoo_type)

    # Un type absent ou non prévu par notre base est ignoré.
    if asset_type is None:
        return None

    yahoo_symbol = str(information.get("symbol") or symbol).upper()

    # La table forex a besoin d'une paire comme EURUSD=X.
    if asset_type == "forex":
        forex_pair = yahoo_symbol.removesuffix("=X")
        if len(forex_pair) != 6:
            return None

    return {
        "symbol": yahoo_symbol,
        "name": (
            information.get("longName")
            or information.get("shortName")
            or symbol
        ),
        "type": asset_type,
        "yahoo_type": yahoo_type,
        "exchange": information.get("exchange"),
        "currency": information.get("currency"),
        "country": information.get("country"),
        "sector": information.get("sector"),
        "industry": information.get("industry"),
    }


def split_crypto_symbol(symbol: str) -> tuple[str | None, str | None]:
    """Transforme BTC-USD en BTC et USD."""

    if "-" not in symbol:
        return None, None

    base, quote = symbol.rsplit("-", 1)
    return base, quote


def split_forex_symbol(symbol: str) -> tuple[str | None, str | None]:
    """Transforme EURUSD=X en EUR et USD."""

    clean_symbol = symbol.removesuffix("=X")

    if len(clean_symbol) != 6:
        return None, None

    return clean_symbol[:3], clean_symbol[3:]


async def create_specific_row(
    db: AsyncSession,
    asset: Asset,
    information: dict,
) -> None:
    """Crée ou met à jour la fiche correspondant au type de l'actif."""

    # La fiche spécialisée reprend l'identifiant de la table assets.
    # Si elle existe déjà, on actualise seulement ses informations Yahoo.

    if asset.ast_type == "stock":
        row = await db.get(Stock, asset.ast_id)
        if row is None:
            row = Stock(sto_ast_id=asset.ast_id)
            db.add(row)

        row.sto_sector = information["sector"]
        row.sto_industry = information["industry"]

    elif asset.ast_type == "crypto":
        row = await db.get(Crypto, asset.ast_id)
        if row is None:
            row = Crypto(
                cry_ast_id=asset.ast_id,
                cry_blockchain=None,
                cry_contract_address=None,
            )
            db.add(row)

        base, quote = split_crypto_symbol(asset.ast_symbol)
        row.cry_base_currency = base
        row.cry_quote_currency = quote

    elif asset.ast_type == "forex":
        row = await db.get(Forex, asset.ast_id)
        base, quote = split_forex_symbol(asset.ast_symbol)

        # Exemple : EURUSD=X donne EUR (base) et USD (devise de cotation).
        # Ces deux valeurs sont obligatoires dans la table forex.
        if base is None or quote is None:
            return

        if row is None:
            row = Forex(for_ast_id=asset.ast_id)
            db.add(row)

        row.for_base_currency = base
        row.for_quote_currency = quote

    elif asset.ast_type == "future":
        row = await db.get(Future, asset.ast_id)
        if row is None:
            row = Future(
                fut_ast_id=asset.ast_id,
                fut_underlying_type=None,
                fut_unit=None,
                fut_contract_size=None,
            )
            db.add(row)

        row.fut_underlying_name = asset.ast_name


async def save_detected_assets(
    db: AsyncSession,
    classification_id: int,
    detected_assets: list[DetectedAsset],
) -> list[Asset]:
    """Vérifie les symboles, crée les actifs et les relie à la classification."""

    saved_assets = []
    used_symbols = set()

    for detected in detected_assets[:10]:
        # 1. Uniformiser le symbole et éviter les doublons dans cette liste.
        requested_symbol = detected.symbol.strip().upper()

        if not requested_symbol or requested_symbol in used_symbols:
            continue

        used_symbols.add(requested_symbol)

        # 2. Vérifier le symbole auprès de Yahoo.
        # [IA-03] Partie technique avec l'aide de l'IA : yfinance est
        # synchrone. to_thread exécute son appel dans un thread séparé,
        # pour que l'API puisse continuer à traiter d'autres demandes.
        information = await asyncio.to_thread(
            get_yahoo_information,
            requested_symbol,
        )

        if information is None:
            continue

        symbol = information["symbol"]
        asset = await db.scalar(
            select(Asset).where(Asset.ast_symbol == symbol)
        )

        # 3. Créer l'actif ou actualiser celui qui existe déjà.
        is_new_asset = asset is None

        if is_new_asset:
            asset = Asset(
                ast_symbol=symbol,
                ast_type=information["type"],
            )
            db.add(asset)
        else:
            if asset.ast_type != information["type"]:
                continue
            asset.ast_updated_at = datetime.now(timezone.utc)

        # Ces champs sont les mêmes pour un actif nouveau ou déjà présent.
        asset.ast_name = information["name"]
        asset.ast_yahoo_type = information["yahoo_type"]
        asset.ast_exchange = information["exchange"]
        asset.ast_currency = information["currency"]
        asset.ast_country = information["country"]
        asset.ast_is_tracked = True

        if is_new_asset:
            # flush obtient l'identifiant créé par la base, sans valider
            # définitivement la transaction. Les autres tables en ont besoin.
            await db.flush()

        # 4. Enregistrer la fiche spécialisée et le lien avec la news classée.
        await create_specific_row(db, asset, information)

        link = await db.get(
            ClassificationAsset,
            (classification_id, asset.ast_id),
        )

        if link is None:
            link = ClassificationAsset(
                cla_cls_id=classification_id,
                cla_ast_id=asset.ast_id,
            )
            db.add(link)

        link.cla_relevance_confidence = detected.confidence
        link.cla_reason = detected.reason

        saved_assets.append(asset)

    # 5. Valider ensemble les actifs, leurs fiches et leurs liens.
    await db.commit()
    return saved_assets
