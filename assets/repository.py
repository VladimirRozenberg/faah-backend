"""Vérification et enregistrement du catalogue dans PostgreSQL."""

from datetime import datetime, timezone
from decimal import Decimal

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assets.catalog import ASSET_CATALOG
from models import Asset, Crypto, Forex, Future, Stock


def get_yahoo_information(symbol: str) -> dict | None:
    """Récupère seulement les informations Yahoo utiles à notre base."""

    try:
        information = yf.Ticker(symbol).get_info()

        if not information.get("quoteType"):
            return None

        return {
            "yahoo_type": information.get("quoteType"),
            "exchange": information.get("exchange"),
            "currency": information.get("currency"),
            "country": information.get("country"),
            "sector": information.get("sector"),
            "industry": information.get("industry"),
        }
    except Exception:
        return None


async def sync_specific_asset(
    db: AsyncSession,
    asset: Asset,
    asset_type: str,
    information: dict,
    yahoo_information: dict,
) -> bool:
    """Crée ou actualise la ligne dans la table spécialisée."""

    if asset_type == "stock":
        row = await db.get(Stock, asset.ast_id)

        if row is None:
            db.add(
                Stock(
                    sto_ast_id=asset.ast_id,
                    sto_sector=yahoo_information["sector"],
                    sto_industry=yahoo_information["industry"],
                )
            )
            return True

        has_changed = False

        if row.sto_sector != yahoo_information["sector"]:
            row.sto_sector = yahoo_information["sector"]
            has_changed = True

        if row.sto_industry != yahoo_information["industry"]:
            row.sto_industry = yahoo_information["industry"]
            has_changed = True

        return has_changed

    elif asset_type == "crypto":
        row = await db.get(Crypto, asset.ast_id)

        if row is None:
            db.add(
                Crypto(
                    cry_ast_id=asset.ast_id,
                    cry_base_currency=information["base"],
                    cry_quote_currency=information["quote"],
                    cry_blockchain=information["blockchain"],
                    cry_contract_address=None,
                )
            )
            return True

        has_changed = False

        if row.cry_base_currency != information["base"]:
            row.cry_base_currency = information["base"]
            has_changed = True

        if row.cry_quote_currency != information["quote"]:
            row.cry_quote_currency = information["quote"]
            has_changed = True

        if row.cry_blockchain != information["blockchain"]:
            row.cry_blockchain = information["blockchain"]
            has_changed = True

        return has_changed

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

    elif asset_type == "future":
        row = await db.get(Future, asset.ast_id)
        contract_size = Decimal(str(information["contract_size"]))

        if row is None:
            db.add(
                Future(
                    fut_ast_id=asset.ast_id,
                    fut_underlying_name=information["name"],
                    fut_underlying_type=information["underlying_type"],
                    fut_unit=information["unit"],
                    fut_contract_size=contract_size,
                )
            )
            return True

        has_changed = False

        if row.fut_underlying_name != information["name"]:
            row.fut_underlying_name = information["name"]
            has_changed = True

        if row.fut_underlying_type != information["underlying_type"]:
            row.fut_underlying_type = information["underlying_type"]
            has_changed = True

        if row.fut_unit != information["unit"]:
            row.fut_unit = information["unit"]
            has_changed = True

        if row.fut_contract_size != contract_size:
            row.fut_contract_size = contract_size
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
                yahoo_information = get_yahoo_information(symbol)

                if yahoo_information is None:
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
                        ast_yahoo_type=yahoo_information["yahoo_type"],
                        ast_exchange=(
                            yahoo_information["exchange"]
                            or information.get("exchange")
                        ),
                        ast_currency=(
                            yahoo_information["currency"]
                            or information.get("quote")
                        ),
                        ast_country=yahoo_information["country"],
                        ast_is_tracked=True,
                    )
                    db.add(asset)

                    # Récupère asset.ast_id avant le commit.
                    await db.flush()

                    await sync_specific_asset(
                        db,
                        asset,
                        asset_type,
                        information,
                        yahoo_information,
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

                yahoo_exchange = (
                    yahoo_information["exchange"]
                    or information.get("exchange")
                )
                yahoo_currency = (
                    yahoo_information["currency"]
                    or information.get("quote")
                )

                if asset.ast_yahoo_type != yahoo_information["yahoo_type"]:
                    asset.ast_yahoo_type = yahoo_information["yahoo_type"]
                    has_changed = True

                if asset.ast_exchange != yahoo_exchange:
                    asset.ast_exchange = yahoo_exchange
                    has_changed = True

                if asset.ast_currency != yahoo_currency:
                    asset.ast_currency = yahoo_currency
                    has_changed = True

                if asset.ast_country != yahoo_information["country"]:
                    asset.ast_country = yahoo_information["country"]
                    has_changed = True

                specific_changed = await sync_specific_asset(
                    db,
                    asset,
                    asset_type,
                    information,
                    yahoo_information,
                )

                if has_changed or specific_changed:
                    asset.ast_updated_at = datetime.now(timezone.utc)
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
