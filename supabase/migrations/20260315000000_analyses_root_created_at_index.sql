-- Optimize top-level analyses reads that filter `company_id IS NULL`
-- and sort newest-first for saved job/history views.

CREATE INDEX IF NOT EXISTS idx_analyses_root_created_at
    ON analyses(created_at DESC)
    WHERE company_id IS NULL;
