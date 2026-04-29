# Environments

This project should now be treated as a multi-environment deployment:

- local development on your machine
- shared non-production infrastructure for development/staging
- a separate production stack with isolated Railway and Supabase projects

Use one codebase across all environments. Isolate by infrastructure, secrets, and runtime env vars rather than by forking the repository.

## Target topology

### Current non-production stack

- Keep the current Railway project and current Supabase project as the shared dev/staging environment.
- It is safe for experimentation, migration rehearsal, and QA.
- Do not treat its secrets, passwords, or data as production-grade defaults.

### Production stack

- Create a new Railway project for production.
- Create two Railway services from the same codebase:
  - web service with `SERVICE_ROLE=web`
  - worker service with `SERVICE_ROLE=worker`
- Create a new Supabase project for production.
- Start production with a clean database unless you explicitly need a historical data backfill.

## Required environment variables

### All environments

- `APP_ENV`
- `LLM_PROVIDER`
- provider API key for the selected LLM

### Local development

- `APP_ENV=development`
- `APP_PASSWORD`
- `SESSION_SECRET`
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` only if you want persistence locally

### Shared staging

- `APP_ENV=staging`
- Use separate staging credentials and passwords from local development
- Point `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` at the shared non-production Supabase project

### Production web

- `APP_ENV=production`
- `SERVICE_ROLE=web`
- `APP_PASSWORD` must be set and must not use the local default
- `SESSION_SECRET` must be set and must not use the placeholder value
- `SUPABASE_URL` must point to the production Supabase project
- `SUPABASE_SERVICE_ROLE_KEY` must be the production service-role key
- `ENABLE_SPECTER_WORKER_SERVICE=true`
- `RESTART_ON_IDLE_AFTER_ANALYSIS=true` is recommended

### Production worker

- `APP_ENV=production`
- `SERVICE_ROLE=worker`
- `SUPABASE_URL` must point to the production Supabase project
- `SUPABASE_SERVICE_ROLE_KEY` must be the production service-role key
- `SPECTER_WORKER_POLL_SECONDS=10` is the current recommended starting point

### Specter MCP credentials (both web and worker, all stacks)

When the Specter MCP intake / augmentation features are enabled, both the web
and worker services need the same Specter OAuth credentials:

- `SPECTER_MCP_URL` — defaults to `https://mcp.tryspecter.com/mcp`; only set if pointing at a non-default endpoint
- `SPECTER_MCP_CLIENT_ID` — minted by `scripts/specter_oauth_login.py`
- `SPECTER_MCP_REFRESH_TOKEN` — bootstrap token; rotated tokens persist to the `mcp_secrets` Supabase table

Both services must point at the same Supabase project so they share the
rotated refresh token (otherwise one service may try to refresh against an
already-rotated token and 401). When the OAuth session reaches its bounded
maximum lifetime, re-run `scripts/specter_oauth_login.py` and replace the
bootstrap value in both env vars.

When `APP_ENV=production`, the app now refuses to start if required production secrets are missing or if the web service still uses the local default password or session secret.

## Production bootstrap checklist

1. Create a new Supabase project for production.
2. Apply every SQL file in [`supabase/migrations`](../supabase/migrations) in filename order.
3. Run `python scripts/supabase_rls_preflight.py` against the production Supabase credentials.
4. Create a new Railway project for production.
5. Create the web and worker services from the same repo/image.
6. Set production env vars separately for each service.
   For shared Supabase vars, you can link the repo to the production Railway project and run:
   `SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... scripts/railway_set_shared_supabase.sh`
7. Deploy the web service and verify the healthcheck.
8. Deploy the worker service and verify it can claim jobs.
9. (Optional, when using Specter MCP) On a workstation, run `python scripts/specter_oauth_login.py`, paste the resulting `SPECTER_MCP_CLIENT_ID` and `SPECTER_MCP_REFRESH_TOKEN` into both the production web and worker env vars.
10. Run a smoke test analysis in production and verify persistence in the production Supabase project.

## Smoke test after cutover

- Login succeeds with the production password.
- Web service returns healthy responses.
- Worker service starts with `SERVICE_ROLE=worker`.
- A new analysis reaches terminal state successfully.
- Results are visible after a web restart.
- Source files are written to the production Supabase storage bucket.
- No production data appears in the staging Supabase project.
