-- Preserve stored casing while preventing case-only duplicate accounts.
-- Existing case-only duplicates must be resolved before applying these indexes.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_unique
    ON users (lower(usr_username));
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_unique
    ON users (lower(usr_email));

COMMIT;
