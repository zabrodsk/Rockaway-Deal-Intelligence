-- Persistent storage for MCP-related rotating credentials.
--
-- Specter MCP rotates refresh tokens on every refresh. The Railway worker
-- needs to write the new token somewhere durable so it survives restarts /
-- redeploys; otherwise every deploy invalidates auth and requires a
-- manual re-mint via scripts/specter_oauth_login.py.
--
-- This table is service-role only — there is no end-user surface to read
-- secrets. RLS is enabled with no policies; only the service-role key
-- bypasses RLS, which is exactly the access we want.

CREATE TABLE IF NOT EXISTS mcp_secrets (
    secret_key TEXT PRIMARY KEY,
    value_text TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mcp_secrets_updated_at
    ON mcp_secrets(updated_at DESC);

ALTER TABLE mcp_secrets ENABLE ROW LEVEL SECURITY;

-- No policies are defined. With RLS enabled and no policies, only the
-- service-role key (which bypasses RLS) can read/write this table. The
-- anon and authenticated roles see zero rows.

COMMENT ON TABLE mcp_secrets IS
    'Service-role-only key/value store for MCP rotating credentials (e.g. Specter refresh tokens).';
COMMENT ON COLUMN mcp_secrets.secret_key IS
    'Logical key, e.g. "specter_mcp_refresh_token".';
