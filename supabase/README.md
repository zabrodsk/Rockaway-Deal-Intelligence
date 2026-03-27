# Supabase Schema

Persistent storage for Rockaway Deal Intelligence analyses.

This repo no longer assumes a single canonical Supabase project. Use a separate
Supabase project for each deployed environment:

- local: optional
- staging: shared non-production project
- production: isolated project

## Setup

1. Create or choose the Supabase project for the target environment.
2. Get the environment's **service_role** key from that project's API settings.
3. Add to `.env`:
   ```
   SUPABASE_URL=https://your-project-ref.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<your_service_role_key>
   ```
4. Migrations to apply in filename order:
   - `20250304000000_init_schema.sql`
   - `20260306000000_extended_persistence.sql`
   - `20260306010000_company_runs.sql`
   - `20260308000000_model_execution_costs.sql`
   - `20260313000000_enable_rls_phase1_internal_tables.sql`
   - `20260313000001_enable_rls_phase2_app_tables.sql`
   - `20260314000000_specter_worker_jobs.sql`
   - `20260314000001_query_performance_indexes.sql`
   - `20260315000000_analyses_root_created_at_index.sql`
5. The app auto-creates the source-files bucket on first upload. Override the bucket name with `SUPABASE_SOURCE_FILES_BUCKET` if needed.

## Behavior

When configured, the app will:

- Persist completed analyses and job metadata to Supabase
- Persist worker/job coordination state used by the dedicated Specter worker
- Upload shared source files to Supabase Storage bucket `analysis-inputs` by default
- Load completed jobs from Supabase on startup in addition to the local JSON fallback
- Fall back to Supabase for `/api/status/{job_id}` and completed analysis payloads when they are not in memory

## Security model

- RLS is enabled on all application tables in `public`.
- No `anon` or `authenticated` policies are created by default.
- The app is expected to access Supabase through the backend using `SUPABASE_SERVICE_ROLE_KEY`.
- Browser clients should keep using the password-protected API instead of querying Supabase tables directly.
- In production, use a dedicated Supabase project and a dedicated service-role key for that environment.

## Preflight and rollback

- Preflight before production rollout:
  ```bash
  python scripts/supabase_rls_preflight.py
  ```
- The preflight uses the same `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` env vars as the app backend.
- Manual rollback SQL lives in `supabase/migrations/rollbacks/20260313_disable_rls_on_app_tables.sql`.
- The rollback file is intentionally not part of the normal migration sequence; do not run it with `supabase db push`.

## API Endpoints

- `GET /api/analyses/{job_id}` - Return analysis results for a completed job
- `GET /api/companies/{company_name}/analyses` - Return analyses for a company by name (requires Supabase)
