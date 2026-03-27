"""Helpers for environment-aware runtime validation."""

from __future__ import annotations

import os


APP_ENV_ALIASES = {
    "dev": "development",
    "development": "development",
    "local": "development",
    "test": "test",
    "testing": "test",
    "stage": "staging",
    "staging": "staging",
    "prod": "production",
    "production": "production",
}
DEFAULT_APP_ENV = "development"
DEFAULT_APP_PASSWORD = "9876"
DEFAULT_SESSION_SECRET = "change-me-session-secret"


def get_app_env() -> str:
    raw = os.getenv("APP_ENV", DEFAULT_APP_ENV).strip().lower()
    return APP_ENV_ALIASES.get(raw, raw or DEFAULT_APP_ENV)


def is_production_env() -> bool:
    return get_app_env() == "production"


def validate_runtime_environment(*, service_role: str = "web") -> None:
    """Raise when production starts with unsafe or incomplete configuration."""

    if not is_production_env():
        return

    normalized_role = (service_role or "web").strip().lower() or "web"
    problems: list[str] = []

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    app_password = os.getenv("APP_PASSWORD", DEFAULT_APP_PASSWORD).strip()
    session_secret = os.getenv("SESSION_SECRET", DEFAULT_SESSION_SECRET).strip()

    if not supabase_url:
        problems.append("SUPABASE_URL must be set when APP_ENV=production.")
    if not supabase_service_role_key:
        problems.append("SUPABASE_SERVICE_ROLE_KEY must be set when APP_ENV=production.")

    if normalized_role != "worker":
        if not app_password:
            problems.append("APP_PASSWORD must be set for the web service in production.")
        elif app_password == DEFAULT_APP_PASSWORD:
            problems.append("APP_PASSWORD cannot use the default local password in production.")

        if not session_secret:
            problems.append("SESSION_SECRET must be set for the web service in production.")
        elif session_secret == DEFAULT_SESSION_SECRET:
            problems.append("SESSION_SECRET cannot use the default placeholder in production.")

    if problems:
        joined = "\n".join(f"- {problem}" for problem in problems)
        raise RuntimeError(f"Invalid production runtime configuration:\n{joined}")
