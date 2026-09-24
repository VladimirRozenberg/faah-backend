from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from db import Base
"""
https://docs.sqlalchemy.org/en/20/tutorial/index.html

Documentation SQLAlchemy ORM et tutorial d'utlisation
"""

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

    usr_balance: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        default=Decimal("0"),
        server_default="0",
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

    ast_yahoo_type: Mapped[str | None] = mapped_column(String)
    ast_exchange: Mapped[str | None] = mapped_column(String)
    ast_currency: Mapped[str | None] = mapped_column(String)
    ast_country: Mapped[str | None] = mapped_column(String)

    ast_logo: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    ast_logo_mime_type: Mapped[str | None] = mapped_column(String)
    ast_logo_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ast_is_tracked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    ast_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    ast_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


# ============================================================
# NICHES
# ============================================================

class Niche(Base):
    __tablename__ = "niches"

    nic_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    nic_name: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )

    nic_category: Mapped[str] = mapped_column(String, nullable=False)
    nic_description: Mapped[str] = mapped_column(Text, nullable=False)


# ============================================================
# ASSET NICHES
# ============================================================

class AssetNiche(Base):
    __tablename__ = "asset_niches"

    ani_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        primary_key=True,
    )

    ani_nic_id: Mapped[int] = mapped_column(
        ForeignKey("niches.nic_id"),
        primary_key=True,
    )

    ani_prm_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompts.prm_id", ondelete="SET NULL")
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

    cry_base_currency: Mapped[str | None] = mapped_column(String)

    cry_quote_currency: Mapped[str | None] = mapped_column(String)

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
# FUTURES
# ============================================================

class Future(Base):
    __tablename__ = "futures"

    fut_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        primary_key=True,
    )

    fut_underlying_name: Mapped[str | None] = mapped_column(String)

    fut_underlying_type: Mapped[str | None] = mapped_column(String)

    fut_unit: Mapped[str | None] = mapped_column(String)

    fut_contract_size: Mapped[Decimal | None] = mapped_column(
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
        unique=True,
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

    pas_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        default=Decimal("0"),
        server_default="0",
        nullable=False,
    )

    pas_average_purchase_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        default=Decimal("0"),
        server_default="0",
        nullable=False,
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

    pas_updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )


# ============================================================
# TRANSACTIONS
# ============================================================

class Transaction(Base):
    """Un achat ou une vente effectué dans un portefeuille."""

    __tablename__ = "transactions"

    id_trans: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    prt_id_trans: Mapped[int] = mapped_column(
        ForeignKey("portfolios.prt_id"),
        nullable=False,
    )

    ast_id_trans: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        nullable=False,
    )

    type_trans: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity_trans: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
    price_trans: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
    fees_trans: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        default=Decimal("0"),
        server_default="0",
        nullable=False,
    )
    currency_trans: Mapped[str] = mapped_column(
        String(10),
        default="USD",
        server_default="USD",
        nullable=False,
    )
    createdAt_trans: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
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
# RSS FEEDS AND SCHEDULER STATE
# ============================================================

class RSSFeed(Base):
    """Database-owned RSS definition and current scheduling state."""

    __tablename__ = "rss_feeds"
    __table_args__ = (
        CheckConstraint(
            "rsf_poll_interval_seconds BETWEEN 300 AND 7200",
            name="chk_rss_feed_poll_interval",
        ),
        CheckConstraint(
            "rsf_status IN ('active', 'paused')",
            name="chk_rss_feed_status",
        ),
        CheckConstraint(
            "rsf_next_poll_trigger IN ('schedule', 'run_now')",
            name="chk_rss_feed_next_trigger",
        ),
        Index("idx_rss_feeds_due", "rsf_status", "rsf_next_poll_at"),
    )

    rsf_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    rsf_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    rsf_url: Mapped[str] = mapped_column(Text, nullable=False)
    rsf_source_prefix: Mapped[str] = mapped_column(String, nullable=False)
    rsf_poll_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        default=3_600,
        server_default="3600",
        nullable=False,
    )
    rsf_status: Mapped[str] = mapped_column(
        String,
        default="active",
        server_default="active",
        nullable=False,
    )
    rsf_last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    rsf_next_poll_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    rsf_next_poll_trigger: Mapped[str] = mapped_column(
        String,
        default="schedule",
        server_default="schedule",
        nullable=False,
    )
    rsf_pending_instruction_id: Mapped[str | None] = mapped_column(String)
    rsf_last_status: Mapped[str | None] = mapped_column(String)
    rsf_last_items_processed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    rsf_last_error: Mapped[str | None] = mapped_column(Text)
    rsf_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    rsf_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class RSSFeedRun(Base):
    """Auditable record of each scheduler-triggered feed execution."""

    __tablename__ = "rss_feed_runs"
    __table_args__ = (
        CheckConstraint(
            "rfr_trigger IN ('schedule', 'run_now')",
            name="chk_rss_feed_run_trigger",
        ),
        CheckConstraint(
            "rfr_status IN ('running', 'succeeded', 'failed')",
            name="chk_rss_feed_run_status",
        ),
        Index(
            "idx_rss_feed_runs_feed_started",
            "rfr_rsf_id",
            "rfr_started_at",
        ),
    )

    rfr_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    rfr_rsf_id: Mapped[int] = mapped_column(
        ForeignKey("rss_feeds.rsf_id", ondelete="CASCADE"),
        nullable=False,
    )
    rfr_trigger: Mapped[str] = mapped_column(String, nullable=False)
    rfr_instruction_id: Mapped[str | None] = mapped_column(String)
    rfr_status: Mapped[str] = mapped_column(String, nullable=False)
    rfr_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    rfr_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    rfr_items_processed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    rfr_error: Mapped[str | None] = mapped_column(Text)


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
# CLASSIFICATION NICHES
# ============================================================

class ClassificationNiche(Base):
    __tablename__ = "classification_niches"

    cln_cls_id: Mapped[int] = mapped_column(
        ForeignKey("source_classifications.cls_id"),
        primary_key=True,
    )

    cln_nic_id: Mapped[int] = mapped_column(
        ForeignKey("niches.nic_id"),
        primary_key=True,
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

    cla_prm_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompts.prm_id", ondelete="SET NULL")
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
# ANALYSIS ASSETS
# ============================================================

class AnalysisAsset(Base):
    __tablename__ = "analysis_assets"

    aas_anl_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.anl_id", ondelete="CASCADE"),
        primary_key=True,
    )

    aas_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id", ondelete="CASCADE"),
        primary_key=True,
    )

    aas_direction: Mapped[str | None] = mapped_column(String)
    aas_confidence: Mapped[int | None] = mapped_column(Integer)
    aas_timeframe: Mapped[str | None] = mapped_column(String)
    aas_reason: Mapped[str | None] = mapped_column(Text)
    aas_price_context: Mapped[dict | None] = mapped_column(JSONB)


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
# ORCHESTRATOR ANALYSIS JOBS
# ============================================================

class OrchestratorAnalysisJob(Base):
    """Persistent targeted research requested by an orchestration cycle."""

    __tablename__ = "orchestrator_analysis_jobs"
    __table_args__ = (
        CheckConstraint(
            "oaj_status IN ('pending', 'running', 'succeeded', 'failed')",
            name="chk_orchestrator_analysis_job_status",
        ),
        CheckConstraint(
            "oaj_priority BETWEEN 1 AND 5",
            name="chk_orchestrator_analysis_job_priority",
        ),
        Index(
            "idx_orchestrator_analysis_jobs_status_requested",
            "oaj_status",
            "oaj_requested_at",
        ),
    )

    oaj_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    oaj_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id"),
        nullable=False,
    )
    oaj_result_anl_id: Mapped[int | None] = mapped_column(
        ForeignKey("analyses.anl_id", ondelete="SET NULL")
    )
    oaj_question: Mapped[str] = mapped_column(Text, nullable=False)
    oaj_reason: Mapped[str] = mapped_column(Text, nullable=False)
    oaj_priority: Mapped[int] = mapped_column(Integer, nullable=False)
    oaj_status: Mapped[str] = mapped_column(
        String,
        default="pending",
        server_default="pending",
        nullable=False,
    )
    oaj_error: Mapped[str | None] = mapped_column(Text)
    oaj_requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    oaj_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    oaj_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


# ============================================================
# PORTFOLIO STRATEGISTS AND MARKET OPPORTUNITIES
# ============================================================

class PortfolioStrategist(Base):
    """Persistent identity and scheduling cursor for one portfolio strategist."""

    __tablename__ = "portfolio_strategists"
    __table_args__ = (
        CheckConstraint(
            "pst_status IN ('active', 'paused')",
            name="chk_portfolio_strategist_status",
        ),
        Index("idx_portfolio_strategists_due", "pst_status", "pst_next_full_review_at"),
    )

    pst_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    pst_prt_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.prt_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    pst_status: Mapped[str] = mapped_column(
        String,
        default="active",
        server_default="active",
        nullable=False,
    )
    pst_instructions: Mapped[str | None] = mapped_column(Text)
    pst_last_signal_id: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    pst_last_full_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    pst_next_full_review_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    pst_last_summary: Mapped[str | None] = mapped_column(Text)
    pst_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    pst_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class MarketOpportunityEvent(Base):
    """A material price movement awaiting shared analysis and dispatch."""

    __tablename__ = "market_opportunity_events"
    __table_args__ = (
        CheckConstraint(
            "moe_event_type IN ('price_rise', 'price_drop')",
            name="chk_market_opportunity_event_type",
        ),
        CheckConstraint(
            "moe_status IN ('detected', 'analyzing', 'analyzed', "
            "'notified', 'failed')",
            name="chk_market_opportunity_event_status",
        ),
        Index("idx_market_opportunity_events_status", "moe_status", "moe_detected_at"),
    )

    moe_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    moe_ast_id: Mapped[int] = mapped_column(
        ForeignKey("assets.ast_id", ondelete="CASCADE"),
        nullable=False,
    )
    moe_result_anl_id: Mapped[int | None] = mapped_column(
        ForeignKey("analyses.anl_id", ondelete="SET NULL")
    )
    moe_event_type: Mapped[str] = mapped_column(String, nullable=False)
    moe_price_before: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    moe_price_after: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    moe_change_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    moe_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    moe_reason: Mapped[str] = mapped_column(Text, nullable=False)
    moe_status: Mapped[str] = mapped_column(
        String,
        default="detected",
        server_default="detected",
        nullable=False,
    )
    moe_error: Mapped[str | None] = mapped_column(Text)
    moe_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    moe_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortfolioStrategistRun(Base):
    """Queue item and audit record for targeted and full strategist reviews."""

    __tablename__ = "portfolio_strategist_runs"
    __table_args__ = (
        CheckConstraint(
            "psr_review_type IN ('targeted_signal', 'targeted_price', 'full')",
            name="chk_portfolio_strategist_run_type",
        ),
        CheckConstraint(
            "psr_status IN ('pending', 'running', 'succeeded', 'failed', 'merged')",
            name="chk_portfolio_strategist_run_status",
        ),
        CheckConstraint(
            "psr_priority BETWEEN 1 AND 5",
            name="chk_portfolio_strategist_run_priority",
        ),
        Index(
            "idx_portfolio_strategist_runs_pending",
            "psr_status",
            "psr_priority",
            "psr_created_at",
        ),
        Index(
            "uq_portfolio_strategist_run_signal",
            "psr_pst_id",
            "psr_sig_id",
            unique=True,
        ),
        Index(
            "uq_portfolio_strategist_run_event",
            "psr_pst_id",
            "psr_moe_id",
            unique=True,
        ),
    )

    psr_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    psr_pst_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_strategists.pst_id", ondelete="CASCADE"),
        nullable=False,
    )
    psr_ast_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.ast_id", ondelete="SET NULL")
    )
    psr_sig_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.sig_id", ondelete="SET NULL")
    )
    psr_moe_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_opportunity_events.moe_id", ondelete="SET NULL")
    )
    psr_result_anl_id: Mapped[int | None] = mapped_column(
        ForeignKey("analyses.anl_id", ondelete="SET NULL")
    )
    psr_prm_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompts.prm_id", ondelete="SET NULL")
    )
    psr_review_type: Mapped[str] = mapped_column(String, nullable=False)
    psr_status: Mapped[str] = mapped_column(
        String,
        default="pending",
        server_default="pending",
        nullable=False,
    )
    psr_priority: Mapped[int] = mapped_column(
        Integer,
        default=3,
        server_default="3",
        nullable=False,
    )
    psr_reason: Mapped[str] = mapped_column(Text, nullable=False)
    psr_decision: Mapped[dict | None] = mapped_column(JSONB)
    psr_error: Mapped[str | None] = mapped_column(Text)
    psr_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    psr_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    psr_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
