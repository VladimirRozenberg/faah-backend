BEGIN;

-- Preserve legacy rows while enforcing the V1 choices for every new or
-- updated portfolio. Unsupported currencies are normalized to USD, while
-- legacy free-form strategy values remain available for later review.
UPDATE public.portfolios
SET prt_base_currency = 'USD'
WHERE prt_base_currency IS DISTINCT FROM 'USD';

ALTER TABLE public.portfolios
    ALTER COLUMN prt_base_currency SET DEFAULT 'USD',
    ALTER COLUMN prt_base_currency SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_portfolio_strategy_type'
          AND conrelid = 'public.portfolios'::regclass
    ) THEN
        ALTER TABLE public.portfolios
            ADD CONSTRAINT chk_portfolio_strategy_type
            CHECK (
                prt_strategy_type IS NULL OR prt_strategy_type IN (
                    'conservative', 'income', 'balanced',
                    'growth', 'aggressive', 'custom'
                )
            ) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_portfolio_base_currency'
          AND conrelid = 'public.portfolios'::regclass
    ) THEN
        ALTER TABLE public.portfolios
            ADD CONSTRAINT chk_portfolio_base_currency
            CHECK (prt_base_currency = 'USD');
    END IF;
END $$;

COMMIT;
