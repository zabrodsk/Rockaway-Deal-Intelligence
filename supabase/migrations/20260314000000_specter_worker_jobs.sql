-- Optional first-class worker lifecycle columns for Specter worker-backed runs.
-- The app continues to read/write worker state via jobs.run_config->worker_state
-- so rollout is backward-compatible even before this migration is applied.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS worker_status TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS active_company_slug TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS active_company_index INTEGER;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS completed_companies INTEGER DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS failed_companies INTEGER DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS total_companies INTEGER;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS run_started_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS run_finished_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS worker_service_enabled BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_jobs_worker_status ON jobs(worker_status);
CREATE INDEX IF NOT EXISTS idx_jobs_last_heartbeat_at ON jobs(last_heartbeat_at);
