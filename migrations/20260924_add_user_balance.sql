-- Ajout sans modification des utilisateurs existants : leur solde initial reste à 0.
BEGIN;


ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS usr_balance NUMERIC(24,8) NOT NULL DEFAULT 0;


COMMIT;


