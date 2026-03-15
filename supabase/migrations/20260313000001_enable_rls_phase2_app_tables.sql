-- Phase 2: enable RLS on persisted app data and history tables.
-- The app remains backend-only for these tables; no public policies are added.

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE pitch_decks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_runs ENABLE ROW LEVEL SECURITY;
