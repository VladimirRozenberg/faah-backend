-- Ajout sans modification des actifs existants : leurs logos restent NULL.
BEGIN;
ALTER TABLE public.assets
    ADD COLUMN IF NOT EXISTS ast_logo BYTEA,
    ADD COLUMN IF NOT EXISTS ast_logo_mime_type VARCHAR,
    ADD COLUMN IF NOT EXISTS ast_logo_last_attempt_at TIMESTAMPTZ;
COMMIT;
