

"""Création du portefeuille, achats et ventes simulés, calculs et historique."""

import asyncio
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from assets.market_data import get_market_asset
from live_market.redis_client import get_latest_quote
from models import (
    Asset,
    Niche,
    Portfolio,
    PortfolioAsset,
    PortfolioAssetTypePreference,
    PortfolioNichePreference,
    PortfolioStrategist,
    Transaction,
    User,
)
from portfolio.schemas import (
    BuyAssetRequest,
    PortfolioCreateRequest,
    PortfolioListResponse,
    PortfolioPositionResponse,
    PortfolioResponse,
    SellAssetRequest,
    TransactionListResponse,
    TransactionResponse,
    AssetTransactionSummary,
)


class AmbiguousPortfolioError(ValueError):
    """Raised when a legacy singular operation has multiple possible targets."""


def round_value(value, digits: int = 4) -> float | None:
    """Arrondit une valeur seulement si elle existe."""

    if value is None:
        return None
    return round(float(value), digits)


async def find_asset(db: AsyncSession, symbol: str) -> Asset:
    """Recherche un actif avec son symbole."""

    symbol = symbol.strip().upper()
    asset = await db.scalar(
        select(Asset).where(Asset.ast_symbol == symbol)
    )

    if asset is None:
        raise LookupError(f"Asset {symbol} does not exist.")

    return asset


async def get_user_portfolio(
    db: AsyncSession,
    user_id: int,
    portfolio_id: int | None = None,
) -> Portfolio:
    """Resolve one owned portfolio, retaining safe legacy default creation."""

    user = await db.get(User, user_id)

    if user is None:
        raise LookupError("This user does not exist.")

    if portfolio_id is not None:
        portfolio = await db.scalar(
            select(Portfolio).where(
                Portfolio.prt_id == portfolio_id,
                Portfolio.prt_usr_id == user_id,
            )
        )
        if portfolio is None:
            raise LookupError("This portfolio does not exist for the user.")
        return portfolio

    portfolios = list(
        (
            await db.scalars(
                select(Portfolio)
                .where(Portfolio.prt_usr_id == user_id)
                .order_by(Portfolio.prt_id)
                .limit(2)
            )
        ).all()
    )
    if len(portfolios) > 1:
        raise AmbiguousPortfolioError(
            "This user has multiple portfolios; specify portfolio_id."
        )
    portfolio = portfolios[0] if portfolios else None

    if portfolio is None:
        # Preserve the original first-access behavior for existing clients.
        portfolio = Portfolio(
            prt_usr_id=user_id,
            prt_name="My portfolio",
            prt_base_currency="USD",
            prt_is_active=True,
        )
        db.add(portfolio)
        await db.flush()
        db.add(PortfolioStrategist(pst_prt_id=portfolio.prt_id))

    return portfolio


async def create_user_portfolio(
    db: AsyncSession,
    user_id: int,
    data: PortfolioCreateRequest,
) -> PortfolioResponse:
    """Create an independently configured portfolio with its own strategist."""

    await get_active_account(db, user_id)
    if data.preferred_niche_ids:
        existing_niche_ids = set(
            (
                await db.scalars(
                    select(Niche.nic_id).where(
                        Niche.nic_id.in_(data.preferred_niche_ids)
                    )
                )
            ).all()
        )
        missing_niche_ids = sorted(
            set(data.preferred_niche_ids) - existing_niche_ids
        )
        if missing_niche_ids:
            values = ", ".join(str(item) for item in missing_niche_ids)
            raise ValueError(f"Unknown preferred niche IDs: {values}.")

    portfolio = Portfolio(
        prt_usr_id=user_id,
        prt_name=data.name.strip(),
        prt_description=(data.description.strip() if data.description else None),
        prt_strategy_type=(
            data.strategy_type.strip() if data.strategy_type else None
        ),
        prt_risk_tolerance=data.risk_tolerance,
        prt_max_position_size_pct=Decimal(str(data.max_position_size_pct)),
        prt_max_open_positions=data.max_open_positions,
        prt_base_currency=data.base_currency.strip().upper(),
        prt_is_active=True,
    )
    db.add(portfolio)
    await db.flush()
    db.add(PortfolioStrategist(pst_prt_id=portfolio.prt_id))
    db.add_all(
        [
            PortfolioAssetTypePreference(
                pat_prt_id=portfolio.prt_id,
                pat_asset_type=asset_type,
            )
            for asset_type in data.preferred_asset_types
        ]
        + [
            PortfolioNichePreference(
                pnp_prt_id=portfolio.prt_id,
                pnp_nic_id=niche_id,
            )
            for niche_id in data.preferred_niche_ids
        ]
    )
    await db.commit()
    return await build_portfolio_response(db, portfolio)


async def list_user_portfolios(
    db: AsyncSession,
    user_id: int,
) -> PortfolioListResponse:
    """Return every portfolio owned by one user without creating a default."""

    await get_active_account(db, user_id)
    portfolios = list(
        (
            await db.scalars(
                select(Portfolio)
                .where(Portfolio.prt_usr_id == user_id)
                .order_by(Portfolio.prt_created_at, Portfolio.prt_id)
            )
        ).all()
    )
    items = [await build_portfolio_response(db, item) for item in portfolios]
    return PortfolioListResponse(count=len(items), items=items)


async def get_current_price(asset: Asset) -> float | None:
    """Cherche le prix dans Redis, puis dans yfinance."""

    if asset.ast_currency != "USD":
        # No FX conversion is available: never label a foreign amount as USD.
        return None

    try:
        quote = await get_latest_quote(asset.ast_symbol)
        if quote is not None:
            return quote.price
    except Exception:
        # Si Redis est indisponible, essayer Yahoo plutôt que bloquer la lecture.
        pass

    try:
        # L'appel Yahoo est synchrone : ce thread évite de bloquer l'API.
        market_asset = await asyncio.to_thread(
            get_market_asset,
            asset,
        )
        return market_asset.last_price
    except Exception:
        # None signifie « prix inconnu », et non « prix égal à zéro ».
        return None


def record_transaction(
    db: AsyncSession,
    portfolio_id: int,
    asset_id: int,
    transaction_type: str,
    quantity: Decimal,
    price: Decimal,
) -> None:
    """Prépare l'enregistrement d'un achat ou d'une vente."""

    db.add(
        Transaction(
            prt_id_trans=portfolio_id,
            ast_id_trans=asset_id,
            type_trans=transaction_type,
            quantity_trans=quantity,
            price_trans=price,
            fees_trans=Decimal("0"),
            currency_trans="USD",
        )
    )


async def save_portfolio_transaction(
    db: AsyncSession,
    portfolio: Portfolio,
    asset: Asset,
    transaction_type: str,
    quantity: Decimal,
    price: Decimal,
) -> PortfolioResponse:
    """Enregistre l'opération et renvoie le portefeuille mis à jour."""

    record_transaction(db, portfolio.prt_id, asset.ast_id, transaction_type, quantity, price)
    portfolio.prt_updated_at = datetime.now()

    # La position a été modifiée dans buy_asset ou sell_asset.
    # Ce commit valide ensemble cette modification et la ligne d'historique.
    await db.commit()
    return await build_portfolio_response(db, portfolio)


async def check_trade_portfolio(db: AsyncSession, portfolio: Portfolio, asset: Asset) -> None:
    """Même règle que le sélecteur Avalonia, vérifiée aussi côté serveur."""
    if not portfolio.prt_is_active:
        raise ValueError("This portfolio is inactive.")
    if portfolio.prt_base_currency != "USD":
        raise ValueError("Only USD portfolios support simulated trading.")
    allowed_types = list((await db.scalars(
        select(PortfolioAssetTypePreference.pat_asset_type)
        .where(PortfolioAssetTypePreference.pat_prt_id == portfolio.prt_id)
    )).all())
    # Aucune préférence = tous les types. Ne pas filtrer sur le nom du portefeuille.
    if allowed_types and asset.ast_type not in allowed_types:
        raise ValueError("This portfolio does not allow this asset type.")


async def buy_asset(
    db: AsyncSession,
    user_id: int,
    data: BuyAssetRequest,
    portfolio_id: int | None = None,
) -> PortfolioResponse:
    """Achète un actif et met la position à jour."""

    account = await get_active_account(db, user_id)
    portfolio = await get_user_portfolio(db, user_id, portfolio_id)
    asset = await find_asset(db, data.symbol)
    await check_trade_portfolio(db, portfolio, asset)

    # Every held asset must be visible to the live opportunity detector.
    if not asset.ast_is_tracked:
        asset.ast_is_tracked = True
        asset.ast_updated_at = datetime.now()

    # Decimal conserve des calculs décimaux pour les montants enregistrés.
    # La conversion par str évite de reprendre les approximations d'un float.
    quantity = Decimal(str(data.quantity))
    price = await execution_price(asset)
    amount = quantity * price
    if amount > account.usr_balance:
        raise ValueError("Insufficient available balance.")
    account.usr_balance -= amount

    position = await db.get(
        PortfolioAsset,
        (portfolio.prt_id, asset.ast_id),
    )

    if position is None:
        # Premier achat de cet actif dans ce portefeuille.
        position = PortfolioAsset(
            pas_prt_id=portfolio.prt_id,
            pas_ast_id=asset.ast_id,
            pas_quantity=quantity,
            pas_average_purchase_price=price,
            pas_is_active=True,
        )
        db.add(position)

    elif not position.pas_is_active:
        # Une position entièrement vendue est réutilisée lors d'un nouvel achat.
        position.pas_quantity = quantity
        position.pas_average_purchase_price = price
        position.pas_is_active = True
        position.pas_updated_at = datetime.now()

    else:
        # Moyenne pondérée des achats.
        # Exemple : 2 unités à 100 + 3 à 120 = 560 / 5 = 112 par unité.
        old_amount = position.pas_quantity * position.pas_average_purchase_price
        new_amount = quantity * price
        total_quantity = position.pas_quantity + quantity

        position.pas_quantity = total_quantity
        position.pas_average_purchase_price = (old_amount + new_amount) / total_quantity
        position.pas_updated_at = datetime.now()

    return await save_portfolio_transaction(
        db, portfolio, asset, "buy", quantity, price,
    )


async def sell_asset(
    db: AsyncSession,
    user_id: int,
    data: SellAssetRequest,
    portfolio_id: int | None = None,
) -> PortfolioResponse:
    """Vend une partie ou la totalité d'une position."""

    account = await get_active_account(db, user_id)
    portfolio = await get_user_portfolio(db, user_id, portfolio_id)
    asset = await find_asset(db, data.symbol)
    await check_trade_portfolio(db, portfolio, asset)

    position = await db.get(
        PortfolioAsset,
        (portfolio.prt_id, asset.ast_id),
    )

    if position is None or not position.pas_is_active:
        raise LookupError(
            f"The portfolio does not hold {asset.ast_symbol}."
        )

    quantity = Decimal(str(data.quantity))
    price = await execution_price(asset)

    if quantity > position.pas_quantity:
        raise ValueError("The sale quantity exceeds the quantity held.")

    account.usr_balance += quantity * price
    position.pas_quantity -= quantity
    position.pas_updated_at = datetime.now()

    if position.pas_quantity == 0:
        # Garder la ligne pour pouvoir la réutiliser, mais ne plus l'afficher.
        position.pas_average_purchase_price = Decimal("0")
        position.pas_is_active = False

    return await save_portfolio_transaction(
        db, portfolio, asset, "sell", quantity, price,
    )


async def create_position_response(
    position: PortfolioAsset,
    asset: Asset,
) -> PortfolioPositionResponse:
    """Calcule les informations affichées pour une position."""

    quantity = float(position.pas_quantity)
    average_price = float(position.pas_average_purchase_price)
    invested = quantity * average_price
    current_price = await get_current_price(asset)
    current_value = None
    profit = None
    profit_percent = None

    if current_price is not None:
        # Gain ou perte des unités encore détenues, pas des ventes passées.
        current_value = quantity * current_price
        profit = current_value - invested

        if invested > 0:
            profit_percent = profit / invested * 100

    return PortfolioPositionResponse(
        asset_id=asset.ast_id,
        symbol=asset.ast_symbol,
        name=asset.ast_name,
        type=asset.ast_type,
        quantity=quantity,
        average_purchase_price=average_price,
        invested_amount=round_value(invested),
        current_price=current_price,
        current_value=round_value(current_value),
        profit_loss=round_value(profit),
        profit_loss_percent=round_value(profit_percent, 2),
    )


async def build_portfolio_response(
    db: AsyncSession,
    portfolio: Portfolio,
) -> PortfolioResponse:
    """Construit le portefeuille envoyé à Avalonia."""

    result = await db.execute(
        select(PortfolioAsset, Asset)
        .join(Asset, Asset.ast_id == PortfolioAsset.pas_ast_id)
        .where(
            PortfolioAsset.pas_prt_id == portfolio.prt_id,
            PortfolioAsset.pas_is_active.is_(True),
        )
        .order_by(Asset.ast_name)
    )

    positions = []
    total_invested = 0.0
    total_current_value = 0.0
    missing_price = False

    for position, asset in result.all():
        item = await create_position_response(position, asset)
        positions.append(item)
        total_invested += item.invested_amount

        if item.current_value is None:
            missing_price = True
        else:
            total_current_value += item.current_value

    if missing_price:
        # Un prix inconnu empêche de donner une valeur totale complète.
        total_current_value = None
        total_profit = None
    else:
        total_profit = total_current_value - total_invested

    account = await db.get(User, portfolio.prt_usr_id)
    preferred_asset_types = list(
        (
            await db.scalars(
                select(PortfolioAssetTypePreference.pat_asset_type)
                .where(
                    PortfolioAssetTypePreference.pat_prt_id == portfolio.prt_id
                )
                .order_by(PortfolioAssetTypePreference.pat_asset_type)
            )
        ).all()
    )
    preferred_niche_ids = list(
        (
            await db.scalars(
                select(PortfolioNichePreference.pnp_nic_id)
                .where(PortfolioNichePreference.pnp_prt_id == portfolio.prt_id)
                .order_by(PortfolioNichePreference.pnp_nic_id)
            )
        ).all()
    )
    return PortfolioResponse(
        balance=float(account.usr_balance),
        id=portfolio.prt_id,
        user_id=portfolio.prt_usr_id,
        name=portfolio.prt_name,
        description=portfolio.prt_description,
        strategy_type=portfolio.prt_strategy_type,
        risk_tolerance=portfolio.prt_risk_tolerance,
        max_position_size_pct=(
            float(portfolio.prt_max_position_size_pct)
            if portfolio.prt_max_position_size_pct is not None
            else None
        ),
        max_open_positions=portfolio.prt_max_open_positions,
        preferred_asset_types=preferred_asset_types,
        preferred_niche_ids=preferred_niche_ids,
        base_currency=portfolio.prt_base_currency or "USD",
        is_active=bool(portfolio.prt_is_active),
        created_at=portfolio.prt_created_at,
        positions_count=len(positions),
        total_invested=round_value(total_invested),
        total_current_value=round_value(total_current_value),
        total_profit_loss=round_value(total_profit),
        positions=positions,
    )


async def read_user_portfolio(
    db: AsyncSession,
    user_id: int,
    portfolio_id: int | None = None,
) -> PortfolioResponse:
    """Retourne le portefeuille d'un utilisateur."""

    portfolio = await get_user_portfolio(db, user_id, portfolio_id)
    response = await build_portfolio_response(db, portfolio)
    await db.commit()
    return response


async def read_transactions(
    db: AsyncSession,
    user_id: int,
    portfolio_id: int | None = None,
) -> TransactionListResponse:
    """Retourne l'historique des achats et des ventes."""

    portfolio = await get_user_portfolio(db, user_id, portfolio_id)

    result = await db.execute(
        select(Transaction, Asset)
        # La jointure ajoute le symbole et le nom de l'actif à chaque opération.
        .join(Asset, Asset.ast_id == Transaction.ast_id_trans)
        .where(Transaction.prt_id_trans == portfolio.prt_id)
        .order_by(Transaction.createdAt_trans.desc())  # Les plus récentes d'abord.
    )

    transactions = []

    for transaction, asset in result.all():
        amount = transaction.quantity_trans * transaction.price_trans

        transactions.append(
            TransactionResponse(
                id=transaction.id_trans,
                symbol=asset.ast_symbol,
                name=asset.ast_name,
                type=transaction.type_trans,
                quantity=float(transaction.quantity_trans),
                price=float(transaction.price_trans),
                fees=float(transaction.fees_trans),
                currency=transaction.currency_trans,
                amount=round_value(amount),
                created_at=transaction.createdAt_trans,
            )
        )

    grouped = await db.execute(
        select(Asset.ast_id, Asset.ast_symbol, Asset.ast_name,
               func.count(Transaction.id_trans).label("transaction_count"),
               func.sum(case((Transaction.type_trans == "buy", 1), else_=0)).label("buy_count"),
               func.sum(case((Transaction.type_trans == "sell", 1), else_=0)).label("sell_count"))
        .join(Transaction, Transaction.ast_id_trans == Asset.ast_id)
        .where(Transaction.prt_id_trans == portfolio.prt_id)
        .group_by(Asset.ast_id, Asset.ast_symbol, Asset.ast_name)
        .order_by(Asset.ast_symbol)
    )
    by_asset = [AssetTransactionSummary(asset_id=row.ast_id, symbol=row.ast_symbol,
        name=row.ast_name, transaction_count=row.transaction_count,
        buy_count=row.buy_count, sell_count=row.sell_count) for row in grouped]
    transactions.sort(key=lambda item: item.created_at.timestamp(), reverse=True)
    await db.commit()
    return TransactionListResponse(
        count=len(transactions),
        transactions=transactions,
        by_asset=by_asset,
    )


async def get_active_account(db: AsyncSession, user_id: int) -> User:
    account = await db.get(User, user_id)
    if account is None or not account.usr_is_active:
        raise LookupError("User not found or disabled.")
    return account


async def execution_price(asset: Asset) -> Decimal:
    price = await get_current_price(asset)
    if price is None:
        raise ValueError("A USD quote is unavailable for this asset.")
    value = Decimal(str(price))
    if not value.is_finite() or value <= 0 or value >= Decimal("10000000000"):
        raise ValueError("Invalid quote for this asset.")
    return value.quantize(Decimal("0.00000001"))


async def deposit_cash(db, user_id, amount):
    """Add simulated funds directly to the user's balance."""
    account = await get_active_account(db, user_id)
    account.usr_balance += amount
    await db.commit()
    return {"balance": float(account.usr_balance), "currency": "USD", "simulation": True}
