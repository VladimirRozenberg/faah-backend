BEGIN;

CREATE TABLE IF NOT EXISTS portfolio_strategist_run_signals (
    psrs_psr_id INTEGER NOT NULL
        REFERENCES portfolio_strategist_runs(psr_id) ON DELETE CASCADE,
    psrs_sig_id INTEGER NOT NULL
        REFERENCES signals(sig_id) ON DELETE CASCADE,
    PRIMARY KEY (psrs_psr_id, psrs_sig_id)
);

INSERT INTO portfolio_strategist_run_signals (psrs_psr_id, psrs_sig_id)
SELECT psr_id, psr_sig_id
FROM portfolio_strategist_runs
WHERE psr_sig_id IS NOT NULL
ON CONFLICT DO NOTHING;

COMMIT;