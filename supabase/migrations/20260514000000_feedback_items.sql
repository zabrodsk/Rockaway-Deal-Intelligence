-- Feedback capture storage for Deal Intelligence.
-- Browser clients submit to the FastAPI backend; no public RLS policies are added.

CREATE TABLE IF NOT EXISTS public.feedback_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_key TEXT NOT NULL DEFAULT 'deal-intelligence',
  category TEXT NOT NULL DEFAULT 'other',
  comment TEXT NOT NULL,
  route TEXT,
  page_url TEXT,
  user_id UUID,
  user_email TEXT,
  user_role TEXT,
  user_display_name TEXT,
  diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
  element_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  screenshot_storage_path TEXT,
  screenshot_content_type TEXT,
  screenshot_size_bytes BIGINT,
  status TEXT NOT NULL DEFAULT 'new',
  priority TEXT NOT NULL DEFAULT 'p2',
  surface TEXT,
  environment TEXT NOT NULL DEFAULT 'production',
  assignee_email TEXT,
  internal_notes TEXT,
  agent_state TEXT NOT NULL DEFAULT 'not-processed',
  agent_summary TEXT,
  agent_confidence NUMERIC,
  agent_suggestions JSONB,
  agent_repro_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
  agent_destination JSONB,
  agent_passes JSONB NOT NULL DEFAULT '[]'::jsonb,
  agent_plan_markdown TEXT,
  agent_evidence_summary TEXT,
  agent_run_log TEXT,
  agent_last_error TEXT,
  agent_artifacts JSONB,
  agent_approved_at TIMESTAMPTZ,
  agent_fixed_at TIMESTAMPTZ,
  agent_ship_log TEXT,
  agent_ship_commit_sha TEXT,
  agent_ship_deploy_log TEXT,
  agent_ship_approved_at TIMESTAMPTZ,
  agent_shipped_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.feedback_items
  ADD COLUMN IF NOT EXISTS project_key TEXT NOT NULL DEFAULT 'deal-intelligence',
  ADD COLUMN IF NOT EXISTS user_id UUID,
  ADD COLUMN IF NOT EXISTS user_role TEXT,
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'new',
  ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'p2',
  ADD COLUMN IF NOT EXISTS surface TEXT,
  ADD COLUMN IF NOT EXISTS environment TEXT NOT NULL DEFAULT 'production',
  ADD COLUMN IF NOT EXISTS assignee_email TEXT,
  ADD COLUMN IF NOT EXISTS internal_notes TEXT,
  ADD COLUMN IF NOT EXISTS agent_state TEXT NOT NULL DEFAULT 'not-processed',
  ADD COLUMN IF NOT EXISTS agent_summary TEXT,
  ADD COLUMN IF NOT EXISTS agent_confidence NUMERIC,
  ADD COLUMN IF NOT EXISTS agent_suggestions JSONB,
  ADD COLUMN IF NOT EXISTS agent_repro_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS agent_destination JSONB,
  ADD COLUMN IF NOT EXISTS agent_passes JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS agent_plan_markdown TEXT,
  ADD COLUMN IF NOT EXISTS agent_evidence_summary TEXT,
  ADD COLUMN IF NOT EXISTS agent_run_log TEXT,
  ADD COLUMN IF NOT EXISTS agent_last_error TEXT,
  ADD COLUMN IF NOT EXISTS agent_artifacts JSONB,
  ADD COLUMN IF NOT EXISTS agent_approved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS agent_fixed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS agent_ship_log TEXT,
  ADD COLUMN IF NOT EXISTS agent_ship_commit_sha TEXT,
  ADD COLUMN IF NOT EXISTS agent_ship_deploy_log TEXT,
  ADD COLUMN IF NOT EXISTS agent_ship_approved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS agent_shipped_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE public.feedback_items
  DROP CONSTRAINT IF EXISTS feedback_items_category_check,
  DROP CONSTRAINT IF EXISTS feedback_items_status_check,
  DROP CONSTRAINT IF EXISTS feedback_items_priority_check,
  DROP CONSTRAINT IF EXISTS feedback_items_surface_check,
  DROP CONSTRAINT IF EXISTS feedback_items_environment_check,
  DROP CONSTRAINT IF EXISTS feedback_items_agent_state_check,
  DROP CONSTRAINT IF EXISTS feedback_items_agent_confidence_check;

ALTER TABLE public.feedback_items
  ADD CONSTRAINT feedback_items_category_check
    CHECK (category IN ('bug', 'improvement', 'confusing', 'other')),
  ADD CONSTRAINT feedback_items_status_check
    CHECK (status IN ('new', 'open', 'snoozed', 'resolved')),
  ADD CONSTRAINT feedback_items_priority_check
    CHECK (priority IN ('p0', 'p1', 'p2', 'p3')),
  ADD CONSTRAINT feedback_items_surface_check
    CHECK (surface IS NULL OR surface IN ('portal', 'dealintel')),
  ADD CONSTRAINT feedback_items_environment_check
    CHECK (environment IN ('production', 'staging', 'local')),
  ADD CONSTRAINT feedback_items_agent_state_check
    CHECK (agent_state IN (
      'not-processed', 'queued', 'analyzing',
      'plan-ready', 'approved', 'fixing', 'fixed',
      'shipping', 'shipped',
      'needs-more-info', 'failed',
      'needs-review', 'proposed', 'resolved'
    )),
  ADD CONSTRAINT feedback_items_agent_confidence_check
    CHECK (agent_confidence IS NULL OR (agent_confidence >= 0 AND agent_confidence <= 1));

CREATE INDEX IF NOT EXISTS idx_feedback_items_project_created_at
  ON public.feedback_items(project_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_items_status_created_at
  ON public.feedback_items(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_items_priority_created_at
  ON public.feedback_items(priority, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_items_agent_state_created_at
  ON public.feedback_items(agent_state, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_items_surface_created_at
  ON public.feedback_items(surface, created_at DESC);

CREATE OR REPLACE FUNCTION public.set_feedback_items_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_feedback_items_updated_at ON public.feedback_items;

CREATE TRIGGER trg_feedback_items_updated_at
  BEFORE UPDATE ON public.feedback_items
  FOR EACH ROW
  EXECUTE FUNCTION public.set_feedback_items_updated_at();

ALTER TABLE public.feedback_items ENABLE ROW LEVEL SECURITY;
