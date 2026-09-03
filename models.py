from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)

from sqlalchemy.orm import Mapped, mapped_column

from db import Base


# ============================================================
# USERS
# ============================================================

class User(Base):
    __tablename__ = "users"

    usr_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    usr_username: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )

    usr_email: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )

    usr_password_hash: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    usr_is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    usr_created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    
    usr_role: Mapped[str] = mapped_column(
        String,
        default="employe",
        server_default="employe",
        nullable=False,
    )
 



# ============================================================
# ASSETS
# ============================================================

class Asset(Base):
    __tablename__ = "assets"

    ast_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    ast_symbol: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )

    ast_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    ast_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    ast_is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    ast_created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )


# ============================================================
# FAVORITES
# ============================================================

class Favorite(Base):
    __tablename__ = "favorites"

    fav_usr_id: Mapped[int] = mapped_column(
        ForeignKey("users.usr_id"),
        primary_key=True,
    )

    fav_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        primary_key=True,
    )

    fav_created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )


# ============================================================
# STOCKS
# ============================================================

class Stock(Base):
    __tablename__ = "stocks"

    sto_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        primary_key=True,
    )

    sto_exchange: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    sto_sector: Mapped[str | None] = mapped_column(String)

    sto_industry: Mapped[str | None] = mapped_column(String)


# ============================================================
# CRYPTO
# ============================================================

class Crypto(Base):
    __tablename__ = "crypto"

    cry_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        primary_key=True,
    )

    cry_blockchain: Mapped[str | None] = mapped_column(String)

    cry_contract_address: Mapped[str | None] = mapped_column(String)


# ============================================================
# FOREX
# ============================================================

class Forex(Base):
    __tablename__ = "forex"

    for_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        primary_key=True,
    )

    for_base_currency: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    for_quote_currency: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )


# ============================================================
# COMMODITIES
# ============================================================

class Commodity(Base):
    __tablename__ = "commodities"

    com_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        primary_key=True,
    )

    com_unit: Mapped[str | None] = mapped_column(String)

    com_contract_size: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2)
    )


# ============================================================
# PORTFOLIOS
# ============================================================

class Portfolio(Base):
    __tablename__ = "portfolios"

    prt_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    prt_usr_id: Mapped[int] = mapped_column(
        ForeignKey("users.usr_id"),
        nullable=False,
    )

    prt_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    prt_description: Mapped[str | None] = mapped_column(Text)

    prt_strategy_type: Mapped[str | None] = mapped_column(String)

    prt_risk_tolerance: Mapped[str | None] = mapped_column(
        String,
        default="medium",
        server_default="medium",
    )

    prt_max_position_size_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        default=Decimal("5.00"),
        server_default="5.00",
    )

    prt_max_open_positions: Mapped[int | None] = mapped_column(
        Integer,
        default=10,
        server_default="10",
    )

    prt_base_currency: Mapped[str | None] = mapped_column(
        String,
        default="USD",
        server_default="USD",
    )

    prt_is_active: Mapped[bool | None] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
    )

    prt_created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    prt_updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )


# ============================================================
# PORTFOLIO ASSETS
# ============================================================

class PortfolioAsset(Base):
    __tablename__ = "portfolio_assets"

    pas_prt_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.prt_id"),
        primary_key=True,
    )

    pas_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        primary_key=True,
    )

    pas_is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    pas_created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )


# ============================================================
# PROMPTS
# ============================================================

class Prompt(Base):
    __tablename__ = "prompts"

    prm_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    prm_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    prm_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    prm_version: Mapped[int | None] = mapped_column(
        Integer,
        default=1,
        server_default="1",
    )

    prm_prompt_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    prm_is_active: Mapped[bool | None] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
    )

    prm_created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    prm_updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )


# ============================================================
# MARKET DATA
# ============================================================

class MarketData(Base):
    __tablename__ = "market_data"

    __table_args__ = (
        UniqueConstraint(
            "mkt_ast_id",
            "mkt_timeframe",
            "mkt_timestamp",
            name="uq_market_data_asset_timeframe_timestamp",
        ),
    )

    mkt_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    mkt_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        nullable=False,
    )

    mkt_timeframe: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    mkt_open: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )

    mkt_high: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )

    mkt_low: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )

    mkt_close: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )

    mkt_volume: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8)
    )

    mkt_timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    mkt_source: Mapped[str | None] = mapped_column(String)


# ============================================================
# DATA SOURCES
# ============================================================

class DataSource(Base):
    __tablename__ = "data_sources"

    src_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    src_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    src_title: Mapped[str | None] = mapped_column(Text)
    src_content: Mapped[str | None] = mapped_column(Text)
    src_original_url: Mapped[str | None] = mapped_column(String)

    src_storage_path: Mapped[str | None] = mapped_column(String)

    src_published_at: Mapped[datetime | None] = mapped_column(DateTime)

    src_is_processed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    src_created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )


# ============================================================
# SOURCE CLASSIFICATIONS
# ============================================================

class SourceClassification(Base):
    __tablename__ = "source_classifications"

    cls_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    cls_src_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.src_id"),
        nullable=False,
    )

    cls_prm_id: Mapped[int] = mapped_column(
        ForeignKey("prompts.prm_id"),
        nullable=False,
    )

    cls_category: Mapped[str | None] = mapped_column(String)

    cls_importance: Mapped[str | None] = mapped_column(String)

    cls_sentiment: Mapped[str | None] = mapped_column(String)

    cls_should_trigger: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    cls_reason: Mapped[str | None] = mapped_column(Text)

    cls_created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )


# ============================================================
# CLASSIFICATION ASSETS
# ============================================================

class ClassificationAsset(Base):
    __tablename__ = "classification_assets"

    cla_cls_id: Mapped[int] = mapped_column(
        ForeignKey("source_classifications.cls_id"),
        primary_key=True,
    )

    cla_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        primary_key=True,
    )

    cla_relevance_confidence: Mapped[int | None] = mapped_column(Integer)

    cla_reason: Mapped[str | None] = mapped_column(Text)


# ============================================================
# ANALYSES
# ============================================================

class Analysis(Base):
    __tablename__ = "analyses"

    anl_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    anl_prm_id: Mapped[int] = mapped_column(
        ForeignKey("prompts.prm_id"),
        nullable=False,
    )

    anl_prt_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolios.prt_id")
    )

    anl_cls_id: Mapped[int | None] = mapped_column(
    ForeignKey(
        "source_classifications.cls_id",
        ondelete="SET NULL",
    ),
    nullable=True,
    index=True,
)

    anl_ast_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.ast_id")
    )

    anl_trigger_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    anl_trigger_reason: Mapped[str | None] = mapped_column(Text)

    anl_response_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    anl_summary: Mapped[str | None] = mapped_column(Text)

    anl_direction: Mapped[str | None] = mapped_column(String)

    anl_market_sentiment: Mapped[str | None] = mapped_column(String)

    anl_confidence: Mapped[int | None] = mapped_column(Integer)

    anl_risk_level: Mapped[str | None] = mapped_column(String)

    anl_timeframe: Mapped[str | None] = mapped_column(String)

    anl_created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )


# ============================================================
# ANALYSIS SOURCES
# ============================================================

class AnalysisSource(Base):
    __tablename__ = "analysis_sources"

    ans_anl_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.anl_id"),
        primary_key=True,
    )

    ans_src_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.src_id"),
        primary_key=True,
    )


# ============================================================
# ANALYSIS INPUTS
# ============================================================

class AnalysisInput(Base):
    __tablename__ = "analysis_inputs"

    inp_anl_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.anl_id"),
        primary_key=True,
    )

    inp_src_anl_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.anl_id"),
        primary_key=True,
    )


# ============================================================
# SIGNALS
# ============================================================

class Signal(Base):
    __tablename__ = "signals"

    sig_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    sig_anl_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.anl_id"),
        nullable=False,
    )

    sig_prt_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolios.prt_id")
    )

    sig_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        nullable=False,
    )

    sig_action: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    sig_entry_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8)
    )

    sig_stop_loss_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8)
    )

    sig_take_profit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8)
    )

    sig_confidence: Mapped[int | None] = mapped_column(Integer)

    sig_timeframe: Mapped[str | None] = mapped_column(String)

    sig_status: Mapped[str | None] = mapped_column(
        String,
        default="active",
        server_default="active",
    )

    sig_expires_at: Mapped[datetime | None] = mapped_column(DateTime)

    sig_created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )