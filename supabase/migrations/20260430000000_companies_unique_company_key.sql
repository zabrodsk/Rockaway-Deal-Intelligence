-- Add the missing non-partial UNIQUE constraint on companies.company_key.
--
-- Symptom that motivated this migration:
--   Production Supabase had a partial unique index from
--   20260306010000_company_runs.sql:
--       CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_company_key
--           ON companies(company_key)
--           WHERE company_key IS NOT NULL;
--   PostgreSQL's `ON CONFLICT (company_key)` inference does not always
--   match against partial indexes when the predicate is not supplied
--   alongside the conflict target. The application's persist code uses
--   `client.table("companies").upsert(payload, on_conflict="company_key")`
--   which translates to `ON CONFLICT (company_key)` with no predicate.
--
--   Result on production: every company upsert raised PostgresError 42P10
--   ("there is no unique or exclusion constraint matching the ON CONFLICT
--   specification"). The exception was swallowed by `_upsert_company`,
--   returning None, which caused the entire per-company persistence chain
--   (companies, pitch_decks, chunks, per-company analyses, company_runs)
--   to silently skip writes. Only the rollup analyses row (with NULL FKs,
--   written by the separate `persist_analysis` function) ever landed.
--
--   Discovered 2026-04-30 during the Specter MCP cutover. Production had
--   never persisted a companies/pitch_decks/chunks row across all time;
--   testing's table apparently received a non-partial unique constraint
--   via an earlier set-up path and was unaffected.
--
-- Fix: add a non-partial UNIQUE constraint on companies.company_key.
-- Idempotent — the DO block checks for any existing non-partial unique
-- index/constraint on company_key first, so this is a no-op on stacks
-- that already have a working constraint (e.g. testing).

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_index i
        JOIN pg_class t ON i.indrelid = t.oid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey)
        WHERE t.relname = 'companies'
          AND a.attname = 'company_key'
          AND i.indisunique
          AND i.indpred IS NULL  -- non-partial (no WHERE clause) only
    ) THEN
        -- Backfill NULL company_key rows so the unique constraint can be
        -- added cleanly. Match the runtime fallback in
        -- web/db.py::_normalize_company_key().
        UPDATE public.companies
        SET company_key = 'name:' || lower(
            regexp_replace(coalesce(name, 'unknown'), '[^a-zA-Z0-9]+', '-', 'g')
        )
        WHERE company_key IS NULL;

        ALTER TABLE public.companies
        ADD CONSTRAINT companies_company_key_key UNIQUE (company_key);

        RAISE NOTICE 'Added unique constraint companies_company_key_key';
    ELSE
        RAISE NOTICE 'Non-partial unique constraint on company_key already exists; skipping';
    END IF;
END $$;
