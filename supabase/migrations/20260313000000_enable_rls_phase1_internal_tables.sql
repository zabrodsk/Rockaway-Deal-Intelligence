-- Phase 1: enable RLS on internal telemetry/control tables first.
-- The backend accesses Supabase with the service_role key, so no public
-- anon/authenticated policies are added in this rollout.

ALTER TABLE analysis_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_controls ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_status_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_errors ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE person_profile_jobs ENABLE ROW LEVEL SECURITY;
