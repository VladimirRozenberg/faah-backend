"""Enregistrement des actions dans PostgreSQL."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from market_data import TECH_STOCKS
from models import Asset, Stock

from db import DbSession


async def sync_stocks(
    db: AsyncSession,
) -> dict[str, int]:
    """Crée ou met à jour les Asset et Stock du catalogue."""

    created = 0
    updated = 0
    unchanged = 0

    try:
        for symbol, metadata in TECH_STOCKS.items():
            # Chercher la partie générale Asset.
            asset_result = await db.execute(
                select(Asset).where(
                    Asset.ast_symbol == symbol
                )
            )

            asset = asset_result.scalar_one_or_none()

            if asset is None:
                # Première étape : créer la classe mère Asset.
                asset = Asset(
                    ast_symbol=symbol,
                    ast_name=metadata["name"],
                    ast_type="stock",
                    ast_is_active=True,
                )

                db.add(asset)

                # Envoie temporairement l'INSERT à PostgreSQL
                # afin de récupérer asset.ast_id.
                await db.flush()

                # Deuxième étape : créer la partie spécialisée Stock.
                stock = Stock(
                    sto_ast_id=asset.ast_id,
                    sto_exchange=metadata["exchange"],
                    sto_sector=None,
                    sto_industry=None,
                )

                db.add(stock)
                created += 1

                # L'action est terminée, on passe à la suivante.
                continue

            # Si le symbole existe déjà avec un autre type,
            # on ne doit pas le transformer automatiquement.
            if asset.ast_type != "stock":
                raise ValueError(
                    f"{symbol} existe déjà avec le type "
                    f"{asset.ast_type}, et non stock."
                )

            has_changed = False

            # Actualiser les informations générales.
            if asset.ast_name != metadata["name"]:
                asset.ast_name = metadata["name"]
                has_changed = True

            if asset.ast_is_active is not True:
                asset.ast_is_active = True
                has_changed = True

            # Chercher la partie spécialisée Stock.
            stock_result = await db.execute(
                select(Stock).where(
                    Stock.sto_ast_id == asset.ast_id
                )
            )

            stock = stock_result.scalar_one_or_none()

            if stock is None:
                # L'Asset existe, mais sa partie Stock est manquante.
                stock = Stock(
                    sto_ast_id=asset.ast_id,
                    sto_exchange=metadata["exchange"],
                    sto_sector=None,
                    sto_industry=None,
                )

                db.add(stock)
                has_changed = True

            else:
                # Actualiser les informations spécifiques au Stock.
                if stock.sto_exchange != metadata["exchange"]:
                    stock.sto_exchange = metadata["exchange"]
                    has_changed = True

            if has_changed:
                updated += 1
            else:
                unchanged += 1

        # Enregistre les Asset et Stock ensemble.
        await db.commit()

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "total": len(TECH_STOCKS),
        }

    except Exception:
        # Si une erreur se produit, aucune modification
        # de cette synchronisation n'est conservée.
        await db.rollback()
        raise