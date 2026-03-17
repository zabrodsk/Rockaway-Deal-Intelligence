-- Shared application settings
-- Used for values that should be consistent across all users, such as the
-- VC investment strategy configured from the Settings modal.

CREATE TABLE IF NOT EXISTS app_settings (
    setting_key TEXT PRIMARY KEY,
    value_text TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_app_settings_updated_at
    ON app_settings(updated_at DESC);

ALTER TABLE app_settings ENABLE ROW LEVEL SECURITY;
