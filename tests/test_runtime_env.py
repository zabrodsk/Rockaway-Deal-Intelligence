import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def test_validate_runtime_environment_allows_non_production_defaults(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    from agent.runtime_env import validate_runtime_environment

    validate_runtime_environment()


def test_validate_runtime_environment_rejects_incomplete_production_web(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    from agent.runtime_env import validate_runtime_environment

    with pytest.raises(RuntimeError) as exc:
        validate_runtime_environment(service_role="web")

    message = str(exc.value)
    assert "SUPABASE_URL must be set" in message
    assert "SUPABASE_SERVICE_ROLE_KEY must be set" in message
    assert "APP_PASSWORD cannot use the default local password" in message
    assert "SESSION_SECRET cannot use the default placeholder" in message


def test_validate_runtime_environment_rejects_default_web_secrets_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SUPABASE_URL", "https://prod.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("APP_PASSWORD", "9876")
    monkeypatch.setenv("SESSION_SECRET", "change-me-session-secret")

    from agent.runtime_env import validate_runtime_environment

    with pytest.raises(RuntimeError) as exc:
        validate_runtime_environment(service_role="web")

    message = str(exc.value)
    assert "APP_PASSWORD cannot use the default local password" in message
    assert "SESSION_SECRET cannot use the default placeholder" in message


def test_validate_runtime_environment_allows_production_worker_without_web_secrets(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SUPABASE_URL", "https://prod.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    from agent.runtime_env import validate_runtime_environment

    validate_runtime_environment(service_role="worker")
