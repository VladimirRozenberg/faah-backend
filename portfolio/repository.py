"""Fonctions qui gèrent le portefeuille dans PostgreSQL."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assets.market_data import market_data_service
from live_market.redis_client import get_latest_quote
from models import Asset, Portfolio, PortfolioAsset, Transaction, User
from portfolio.schemas import (
    BuyAssetRequest,
    PortfolioPositionResponse,
    PortfolioResponse,
    SellAssetRequest,
    TransactionListResponse,
    TransactionResponse,
)


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
        raise LookupError(f"L'actif {symbol} n'existe pas.")

    return asset


async def get_user_portfolio(db: AsyncSession, user_id: int) -> Portfolio:
    """Retourne le portefeuille ou le crée s'il n'existe pas."""

    user = await db.get(User, user_id)

    if user is None or not user.usr_is_active:
        raise LookupError("Cet utilisateur n'existe pas.")

    portfolio = await db.scalar(
        select(Portfolio).where(Portfolio.prt_usr_id == user_id)
    )

    if portfolio is None:
        portfolio = Portfolio(
            prt_usr_id=user_id,
            prt_name="Mon portefeuille",
            prt_base_currency="USD",
            prt_is_active=True,
        )
        db.add(portfolio)
        await db.commit()
        await db.refresh(portfolio)

    return portfolio


async def get_current_price(symbol: str) -> float | None:
    """Cherche le prix dans Redis, puis dans yfinance."""

    try:
        quote = await get_latest_quote(symbol)
        if quote is not None:
            return quote.price
    except Exception:
        pass

    try:
        return market_data_service.get_asset(symbol).last_price
    except Exception:
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


async def buy_asset(
    db: AsyncSession,
    user_id: int,
    data: BuyAssetRequest,
) -> PortfolioResponse:
    """Achète un actif et met la position à jour."""

    portfolio = await get_user_portfolio(db, user_id)
    asset = await find_asset(db, data.symbol)

    quantity = Decimal(str(data.quantity))
    price = Decimal(str(data.purchase_price))

    position = await db.get(
        PortfolioAsset,
        (portfolio.prt_id, asset.ast_id),
    )

    if position is None:
        position = PortfolioAsset(
            pas_prt_id=portfolio.prt_id,
            pas_ast_id=asset.ast_id,
            pas_quantity=quantity,
            pas_average_purchase_price=price,
            pas_is_active=True,
        )
        db.add(position)

    elif not position.pas_is_active:
        position.pas_quantity = quantity
        position.pas_average_purchase_price = price
        position.pas_is_active = True
        position.pas_updated_at = datetime.now()

    else:
        old_amount = (
            position.pas_quantity
            * position.pas_average_purchase_price
        )
        new_amount = quantity * price

        position.pas_quantity += quantity
        position.pas_average_purchase_price = (
            old_amount + new_amount
        ) / position.pas_quantity
        position.pas_updated_at = datetime.now()

    record_transaction(
        db,
        portfolio.prt_id,
        asset.ast_id,
        "buy",
        quantity,
        price,
    )

    portfolio.prt_updated_at = datetime.now()
    await db.commit()

    return await build_portfolio_response(db, portfolio)


async def sell_asset(
    db: AsyncSession,
    user_id: int,
    data: SellAssetRequest,
) -> PortfolioResponse:
    """Vend une partie ou la totalité d'une position."""

    portfolio = await get_user_portfolio(db, user_id)
    asset = await find_asset(db, data.symbol)

    position = await db.get(
        PortfolioAsset,
        (portfolio.prt_id, asset.ast_id),
    )

    if position is None or not position.pas_is_active:
        raise LookupError(
            f"Le portefeuille ne possède pas {asset.ast_symbol}."
        )

    quantity = Decimal(str(data.quantity))
    price = Decimal(str(data.sale_price))

    if quantity > position.pas_quantity:
        raise ValueError("La quantité vendue dépasse la quantité possédée.")

    position.pas_quantity -= quantity
    position.pas_updated_at = datetime.now()

    if position.pas_quantity == 0:
        position.pas_average_purchase_price = Decimal("0")
        position.pas_is_active = False

    record_transaction(
        db,
        portfolio.prt_id,
        asset.ast_id,
        "sell",
        quantity,
        price,
    )

    portfolio.prt_updated_at = datetime.now()
    await db.commit()

    return await build_portfolio_response(db, portfolio)


async def create_position_response(
    position: PortfolioAsset,
    asset: Asset,
) -> PortfolioPositionResponse:
    """Calcule les informations affichées pour une position."""

    quantity = float(position.pas_quantity)
    average_price = float(position.pas_average_purchase_price)
    invested = quantity * average_price
    current_price = await get_current_price(asset.ast_symbol)
    current_value = None
    profit = None
    profit_percent = None

    if current_price is not None:
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
        current_total = None
        total_profit = None
    else:
        current_total = total_current_value
        total_profit = total_current_value - total_invested

    return PortfolioResponse(
        id=portfolio.prt_id,
        user_id=portfolio.prt_usr_id,
        name=portfolio.prt_name,
        description=portfolio.prt_description,
        base_currency=portfolio.prt_base_currency or "USD",
        is_active=bool(portfolio.prt_is_active),
        created_at=portfolio.prt_created_at,
        positions_count=len(positions),
        total_invested=round_value(total_invested),
        total_current_value=round_value(current_total),
        total_profit_loss=round_value(total_profit),
        positions=positions,
    )


async def read_user_portfolio(
    db: AsyncSession,
    user_id: int,
) -> PortfolioResponse:
    """Retourne le portefeuille d'un utilisateur."""

    portfolio = await get_user_portfolio(db, user_id)
    return await build_portfolio_response(db, portfolio)


async def read_transactions(
    db: AsyncSession,
    user_id: int,
) -> TransactionListResponse:
    """Retourne l'historique des achats et des ventes."""

    portfolio = await get_user_portfolio(db, user_id)

    result = await db.execute(
        select(Transaction, Asset)
        .join(Asset, Asset.ast_id == Transaction.ast_id_trans)
        .where(Transaction.prt_id_trans == portfolio.prt_id)
        .order_by(Transaction.createdAt_trans.desc())
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

    return TransactionListResponse(
        count=len(transactions),
        transactions=transactions,
    )
