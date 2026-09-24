BEGIN;

-- Older FAAH databases created portfolio_assets before position quantities and
-- average prices were added to the application model. Strategists need the same
-- position data as the portfolio API, so align those databases non-destructively.
ALTER TABLE portfolio_assets
    ADD COLUMN IF NOT EXISTS pas_quantity NUMERIC(18,8) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pas_average_purchase_price NUMERIC(18,8) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pas_updated_at TIMESTAMP NOT NULL DEFAULT NOW();

-- Preserve data from the first demo name. PostgreSQL carries foreign keys and
-- identity sequences across these table and column renames.
DO $$
BEGIN
    IF to_regclass('public.portfolio_strategists') IS NULL
       AND to_regclass('public.portfolio_guardians') IS NOT NULL THEN
        ALTER TABLE portfolio_guardians RENAME TO portfolio_strategists;
    END IF;

    IF to_regclass('public.portfolio_strategists') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public'
             AND table_name = 'portfolio_strategists'
             AND column_name = 'pgr_id'
       ) THEN
        ALTER TABLE portfolio_strategists RENAME COLUMN pgr_id TO pst_id;
        ALTER TABLE portfolio_strategists RENAME COLUMN pgr_prt_id TO pst_prt_id;
        ALTER TABLE portfolio_strategists RENAME COLUMN pgr_status TO pst_status;
        ALTER TABLE portfolio_strategists RENAME COLUMN pgr_instructions TO pst_instructions;
        ALTER TABLE portfolio_strategists RENAME COLUMN pgr_last_signal_id TO pst_last_signal_id;
        ALTER TABLE portfolio_strategists RENAME COLUMN pgr_last_full_review_at TO pst_last_full_review_at;
        ALTER TABLE portfolio_strategists RENAME COLUMN pgr_next_full_review_at TO pst_next_full_review_at;
        ALTER TABLE portfolio_strategists RENAME COLUMN pgr_last_summary TO pst_last_summary;
        ALTER TABLE portfolio_strategists RENAME COLUMN pgr_created_at TO pst_created_at;
        ALTER TABLE portfolio_strategists RENAME COLUMN pgr_updated_at TO pst_updated_at;
    END IF;

    IF to_regclass('public.portfolio_strategist_runs') IS NULL
       AND to_regclass('public.portfolio_guardian_runs') IS NOT NULL THEN
        ALTER TABLE portfolio_guardian_runs RENAME TO portfolio_strategist_runs;
    END IF;

    IF to_regclass('public.portfolio_strategist_runs') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public'
             AND table_name = 'portfolio_strategist_runs'
             AND column_name = 'pgrn_id'
       ) THEN
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_id TO psr_id;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_pgr_id TO psr_pst_id;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_ast_id TO psr_ast_id;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_sig_id TO psr_sig_id;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_moe_id TO psr_moe_id;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_result_anl_id TO psr_result_anl_id;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_review_type TO psr_review_type;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_status TO psr_status;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_priority TO psr_priority;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_reason TO psr_reason;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_decision TO psr_decision;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_error TO psr_error;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_created_at TO psr_created_at;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_started_at TO psr_started_at;
        ALTER TABLE portfolio_strategist_runs RENAME COLUMN pgrn_completed_at TO psr_completed_at;
    END IF;
END $$;

ALTER INDEX IF EXISTS idx_portfolio_guardians_due
    RENAME TO idx_portfolio_strategists_due;
ALTER INDEX IF EXISTS idx_portfolio_guardian_runs_pending
    RENAME TO idx_portfolio_strategist_runs_pending;
ALTER INDEX IF EXISTS uq_portfolio_guardian_run_signal
    RENAME TO uq_portfolio_strategist_run_signal;
ALTER INDEX IF EXISTS uq_portfolio_guardian_run_event
    RENAME TO uq_portfolio_strategist_run_event;

DO $$
DECLARE
    item RECORD;
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_portfolio_guardian_status'
    ) THEN
        ALTER TABLE portfolio_strategists
            RENAME CONSTRAINT chk_portfolio_guardian_status
            TO chk_portfolio_strategist_status;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_portfolio_guardian_run_type'
    ) THEN
        ALTER TABLE portfolio_strategist_runs
            RENAME CONSTRAINT chk_portfolio_guardian_run_type
            TO chk_portfolio_strategist_run_type;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_portfolio_guardian_run_status'
    ) THEN
        ALTER TABLE portfolio_strategist_runs
            RENAME CONSTRAINT chk_portfolio_guardian_run_status
            TO chk_portfolio_strategist_run_status;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_portfolio_guardian_run_priority'
    ) THEN
        ALTER TABLE portfolio_strategist_runs
            RENAME CONSTRAINT chk_portfolio_guardian_run_priority
            TO chk_portfolio_strategist_run_priority;
    END IF;

    FOR item IN
        SELECT * FROM (VALUES
            ('portfolio_strategists', 'portfolio_guardians_pkey', 'portfolio_strategists_pkey'),
            ('portfolio_strategists', 'portfolio_guardians_pgr_prt_id_key', 'portfolio_strategists_pst_prt_id_key'),
            ('portfolio_strategists', 'portfolio_guardians_pgr_prt_id_fkey', 'portfolio_strategists_pst_prt_id_fkey'),
            ('portfolio_strategist_runs', 'portfolio_guardian_runs_pkey', 'portfolio_strategist_runs_pkey'),
            ('portfolio_strategist_runs', 'portfolio_guardian_runs_pgrn_pgr_id_fkey', 'portfolio_strategist_runs_psr_pst_id_fkey'),
            ('portfolio_strategist_runs', 'portfolio_guardian_runs_pgrn_ast_id_fkey', 'portfolio_strategist_runs_psr_ast_id_fkey'),
            ('portfolio_strategist_runs', 'portfolio_guardian_runs_pgrn_sig_id_fkey', 'portfolio_strategist_runs_psr_sig_id_fkey'),
            ('portfolio_strategist_runs', 'portfolio_guardian_runs_pgrn_moe_id_fkey', 'portfolio_strategist_runs_psr_moe_id_fkey'),
            ('portfolio_strategist_runs', 'portfolio_guardian_runs_pgrn_result_anl_id_fkey', 'portfolio_strategist_runs_psr_result_anl_id_fkey')
        ) AS names(table_name, old_name, new_name)
    LOOP
        IF EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = item.old_name
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I RENAME CONSTRAINT %I TO %I',
                item.table_name,
                item.old_name,
                item.new_name
            );
        END IF;
    END LOOP;
END $$;

CREATE TABLE IF NOT EXISTS portfolio_strategists (
    pst_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    pst_prt_id INTEGER NOT NULL UNIQUE
        REFERENCES portfolios(prt_id) ON DELETE CASCADE,
    pst_status VARCHAR NOT NULL DEFAULT 'active',
    pst_instructions TEXT,
    pst_last_signal_id INTEGER NOT NULL DEFAULT 0,
    pst_last_full_review_at TIMESTAMPTZ,
    pst_next_full_review_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pst_last_summary TEXT,
    pst_created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pst_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_portfolio_strategist_status
        CHECK (pst_status IN ('active', 'paused'))
);

CREATE INDEX IF NOT EXISTS idx_portfolio_strategists_due
    ON portfolio_strategists (pst_status, pst_next_full_review_at);

CREATE TABLE IF NOT EXISTS market_opportunity_events (
    moe_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    moe_ast_id INTEGER NOT NULL REFERENCES assets(ast_id) ON DELETE CASCADE,
    moe_result_anl_id INTEGER REFERENCES analyses(anl_id) ON DELETE SET NULL,
    moe_event_type VARCHAR NOT NULL,
    moe_price_before NUMERIC(18,8) NOT NULL,
    moe_price_after NUMERIC(18,8) NOT NULL,
    moe_change_pct NUMERIC(10,4) NOT NULL,
    moe_window_seconds INTEGER NOT NULL,
    moe_reason TEXT NOT NULL,
    moe_status VARCHAR NOT NULL DEFAULT 'detected',
    moe_error TEXT,
    moe_detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    moe_analyzed_at TIMESTAMPTZ,
    CONSTRAINT chk_market_opportunity_event_type
        CHECK (moe_event_type IN ('price_rise', 'price_drop')),
    CONSTRAINT chk_market_opportunity_event_status
        CHECK (moe_status IN ('detected', 'analyzing', 'analyzed', 'notified', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_market_opportunity_events_status
    ON market_opportunity_events (moe_status, moe_detected_at);

CREATE TABLE IF NOT EXISTS portfolio_strategist_runs (
    psr_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    psr_pst_id INTEGER NOT NULL
        REFERENCES portfolio_strategists(pst_id) ON DELETE CASCADE,
    psr_ast_id INTEGER REFERENCES assets(ast_id) ON DELETE SET NULL,
    psr_sig_id INTEGER REFERENCES signals(sig_id) ON DELETE SET NULL,
    psr_moe_id INTEGER REFERENCES market_opportunity_events(moe_id) ON DELETE SET NULL,
    psr_result_anl_id INTEGER REFERENCES analyses(anl_id) ON DELETE SET NULL,
    psr_prm_id INTEGER REFERENCES prompts(prm_id) ON DELETE SET NULL,
    psr_review_type VARCHAR NOT NULL,
    psr_status VARCHAR NOT NULL DEFAULT 'pending',
    psr_priority INTEGER NOT NULL DEFAULT 3,
    psr_reason TEXT NOT NULL,
    psr_decision JSONB,
    psr_error TEXT,
    psr_created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    psr_started_at TIMESTAMPTZ,
    psr_completed_at TIMESTAMPTZ,
    CONSTRAINT chk_portfolio_strategist_run_type
        CHECK (psr_review_type IN ('targeted_signal', 'targeted_price', 'full')),
    CONSTRAINT chk_portfolio_strategist_run_status
        CHECK (psr_status IN ('pending', 'running', 'succeeded', 'failed', 'merged')),
    CONSTRAINT chk_portfolio_strategist_run_priority
        CHECK (psr_priority BETWEEN 1 AND 5)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_strategist_runs_pending
    ON portfolio_strategist_runs (psr_status, psr_priority DESC, psr_created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_strategist_run_signal
    ON portfolio_strategist_runs (psr_pst_id, psr_sig_id)
    WHERE psr_sig_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_strategist_run_event
    ON portfolio_strategist_runs (psr_pst_id, psr_moe_id)
    WHERE psr_moe_id IS NOT NULL;

-- Existing active portfolios receive a strategist immediately. Portfolio assets
-- are automatically included in the live quote stream.
INSERT INTO portfolio_strategists (pst_prt_id)
SELECT prt_id FROM portfolios WHERE prt_is_active IS TRUE
ON CONFLICT (pst_prt_id) DO NOTHING;

UPDATE assets
SET ast_is_tracked = TRUE,
    ast_updated_at = NOW()
WHERE ast_id IN (
    SELECT pas_ast_id
    FROM portfolio_assets
    WHERE pas_is_active IS TRUE
);

UPDATE analyses
SET anl_trigger_type = regexp_replace(
    anl_trigger_type,
    'guardian_',
    'strategist_',
    'gi'
)
WHERE anl_trigger_type ILIKE 'guardian_%';

UPDATE prompts
SET prm_name = regexp_replace(prm_name, 'guardian', 'strategist', 'gi'),
    prm_type = regexp_replace(prm_type, 'guardian_', 'strategist_', 'gi'),
    prm_prompt_text = regexp_replace(
        prm_prompt_text,
        'guardian',
        'strategist',
        'gi'
    )
WHERE prm_name ILIKE '%guardian%'
   OR prm_type LIKE 'guardian_%'
   OR prm_prompt_text ILIKE '%guardian%';

COMMIT;
