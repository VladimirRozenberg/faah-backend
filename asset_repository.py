"""Vérification et enregistrement du catalogue dans PostgreSQL."""

from decimal import Decimal

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from asset_catalog import ASSET_CATALOG
from models import Asset, Commodity, Crypto, Forex, Stock


def symbol_exists(symbol: str) -> bool:
    """Vérifie que yfinance retourne des données pour le symbole."""

    try:
        history = yf.Ticker(symbol).history(
            period="5d",
            interval="1d",
            auto_adjust=False,
        )
        return not history.empty
    except Exception:
        return False


async def sync_specific_asset(
    db: AsyncSession,
    asset: Asset,
    asset_type: str,
    information: dict,
) -> bool:
    """Crée ou actualise la ligne dans la table spécialisée."""

    if asset_type == "stock":
        row = await db.get(Stock, asset.ast_id)

        if row is None:
            db.add(
                Stock(
                    sto_ast_id=asset.ast_id,
                    sto_exchange=information["exchange"],
                    sto_sector=None,
                    sto_industry=None,
                )
            )
            return True

        if row.sto_exchange != information["exchange"]:
            row.sto_exchange = information["exchange"]
            return True

    elif asset_type == "crypto":
        row = await db.get(Crypto, asset.ast_id)

        if row is None:
            db.add(
                Crypto(
                    cry_ast_id=asset.ast_id,
                    cry_blockchain=information["blockchain"],
                    cry_contract_address=None,
                )
            )
            return True

        if row.cry_blockchain != information["blockchain"]:
            row.cry_blockchain = information["blockchain"]
            return True

    elif asset_type == "forex":
        row = await db.get(Forex, asset.ast_id)

        if row is None:
            db.add(
                Forex(
                    for_ast_id=asset.ast_id,
                    for_base_currency=information["base"],
                    for_quote_currency=information["quote"],
                )
            )
            return True

        has_changed = False

        if row.for_base_currency != information["base"]:
            row.for_base_currency = information["base"]
            has_changed = True

        if row.for_quote_currency != information["quote"]:
            row.for_quote_currency = information["quote"]
            has_changed = True

        return has_changed

    elif asset_type == "commodity":
        row = await db.get(Commodity, asset.ast_id)
        contract_size = Decimal(str(information["contract_size"]))

        if row is None:
            db.add(
                Commodity(
                    com_ast_id=asset.ast_id,
                    com_unit=information["unit"],
                    com_contract_size=contract_size,
                )
            )
            return True

        has_changed = False

        if row.com_unit != information["unit"]:
            row.com_unit = information["unit"]
            has_changed = True

        if row.com_contract_size != contract_size:
            row.com_contract_size = contract_size
            has_changed = True

        return has_changed

    else:
        raise ValueError(f"Type d'actif inconnu : {asset_type}")

    return False


async def sync_all_assets(db: AsyncSession) -> dict[str, int]:
    """Crée ou actualise tous les actifs du catalogue."""

    created = 0
    updated = 0
    unchanged = 0
    unavailable = 0
    total = 0

    try:
        for asset_type, assets in ASSET_CATALOG.items():
            total += len(assets)

            for symbol, information in assets.items():
                if not symbol_exists(symbol):
                    unavailable += 1
                    continue

                asset = await db.scalar(
                    select(Asset).where(Asset.ast_symbol == symbol)
                )

                if asset is None:
                    asset = Asset(
                        ast_symbol=symbol,
                        ast_name=information["name"],
                        ast_type=asset_type,
                        ast_is_active=True,
                    )
                    db.add(asset)

                    # Récupère asset.ast_id avant le commit.
                    await db.flush()

                    await sync_specific_asset(
                        db,
                        asset,
                        asset_type,
                        information,
                    )
                    created += 1
                    continue

                if asset.ast_type != asset_type:
                    raise ValueError(
                        f"{symbol} existe déjà avec le type "
                        f"{asset.ast_type}, et non {asset_type}."
                    )

                has_changed = False

                if asset.ast_name != information["name"]:
                    asset.ast_name = information["name"]
                    has_changed = True

                if asset.ast_is_active is not True:
                    asset.ast_is_active = True
                    has_changed = True

                specific_changed = await sync_specific_asset(
                    db,
                    asset,
                    asset_type,
                    information,
                )

                if has_changed or specific_changed:
                    updated += 1
                else:
                    unchanged += 1

        await db.commit()

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "unavailable": unavailable,
            "total": total,
        }

    except Exception:
        await db.rollback()
        raise
