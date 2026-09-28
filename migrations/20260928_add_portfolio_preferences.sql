BEGIN;

CREATE TABLE IF NOT EXISTS portfolio_asset_type_preferences (
    pat_prt_id INTEGER NOT NULL
        REFERENCES portfolios(prt_id) ON DELETE CASCADE,
    pat_asset_type VARCHAR NOT NULL,
    PRIMARY KEY (pat_prt_id, pat_asset_type),
    CONSTRAINT chk_portfolio_asset_type_preference
        CHECK (pat_asset_type IN ('stock', 'crypto', 'forex', 'future'))
);

CREATE TABLE IF NOT EXISTS portfolio_niche_preferences (
    pnp_prt_id INTEGER NOT NULL
        REFERENCES portfolios(prt_id) ON DELETE CASCADE,
    pnp_nic_id INTEGER NOT NULL
        REFERENCES niches(nic_id) ON DELETE CASCADE,
    PRIMARY KEY (pnp_prt_id, pnp_nic_id)
);

COMMIT;
