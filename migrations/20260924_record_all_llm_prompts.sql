BEGIN;

ALTER TABLE asset_niches
    ADD COLUMN IF NOT EXISTS ani_prm_id INTEGER;

ALTER TABLE classification_assets
    ADD COLUMN IF NOT EXISTS cla_prm_id INTEGER;

ALTER TABLE portfolio_strategist_runs
    ADD COLUMN IF NOT EXISTS psr_prm_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_asset_niches_prompt'
    ) THEN
        ALTER TABLE asset_niches
            ADD CONSTRAINT fk_asset_niches_prompt
            FOREIGN KEY (ani_prm_id)
            REFERENCES prompts(prm_id)
            ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_classification_assets_prompt'
    ) THEN
        ALTER TABLE classification_assets
            ADD CONSTRAINT fk_classification_assets_prompt
            FOREIGN KEY (cla_prm_id)
            REFERENCES prompts(prm_id)
            ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_portfolio_strategist_runs_prompt'
    ) THEN
        ALTER TABLE portfolio_strategist_runs
            ADD CONSTRAINT fk_portfolio_strategist_runs_prompt
            FOREIGN KEY (psr_prm_id)
            REFERENCES prompts(prm_id)
            ON DELETE SET NULL;
    END IF;
END $$;

COMMIT;
