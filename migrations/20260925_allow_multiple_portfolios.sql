BEGIN;

-- Earlier schemas enforced one portfolio per user. Drop any single-column
-- UNIQUE constraint on prt_usr_id regardless of its generated constraint name.
DO $$
DECLARE
    item RECORD;
BEGIN
    FOR item IN
        SELECT constraint_row.conname
        FROM pg_constraint AS constraint_row
        JOIN pg_attribute AS attribute_row
          ON attribute_row.attrelid = constraint_row.conrelid
         AND attribute_row.attnum = constraint_row.conkey[1]
        WHERE constraint_row.conrelid = 'portfolios'::regclass
          AND constraint_row.contype = 'u'
          AND cardinality(constraint_row.conkey) = 1
          AND attribute_row.attname = 'prt_usr_id'
    LOOP
        EXECUTE format(
            'ALTER TABLE portfolios DROP CONSTRAINT %I',
            item.conname
        );
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS idx_portfolios_user
    ON portfolios (prt_usr_id);

COMMIT;
