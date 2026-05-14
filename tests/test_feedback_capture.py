"""Tests for authenticated Deal Intelligence feedback capture."""

import base64
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import pytest
from fastapi.testclient import TestClient

import web.db as real_db
from web.app import app

_FAKE_USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_FAKE_TOKEN = "fake.jwt.token"
_AUTH_HEADER = {"Authorization": f"Bearer {_FAKE_TOKEN}"}


def _profile(**overrides):
    base = {
        "id": _FAKE_USER_ID,
        "role": "vc",
        "display_name": "Jane Investor",
        "approved": True,
    }
    base.update(overrides)
    return base


def _make_mock_db(*, profile=None, supabase_user=None):
    m = MagicMock()
    m.FeedbackScreenshotError = real_db.FeedbackScreenshotError
    m.get_authenticated_supabase_user.return_value = (
        supabase_user or {"id": _FAKE_USER_ID, "email": "jane@rockawayx.com"}
    )
    m.get_user_profile.return_value = profile or _profile()
    m.decode_feedback_screenshot.side_effect = real_db.decode_feedback_screenshot
    m.upload_feedback_screenshot.return_value = "feedback/screenshots/fixed.webp"
    m.create_feedback_item.side_effect = lambda payload: payload
    return m


def test_feedback_requires_comment():
    import web.app as app_module

    mock_db = _make_mock_db()
    with patch.object(app_module, "db", mock_db):
        with TestClient(app) as client:
            resp = client.post("/api/feedback", json={"comment": "   "}, headers=_AUTH_HEADER)

    assert resp.status_code == 400
    assert resp.json()["detail"] == "comment is required"
    mock_db.create_feedback_item.assert_not_called()


def test_feedback_persists_project_identity_and_context(monkeypatch):
    import web.app as app_module

    monkeypatch.setenv("APP_ENV", "testing")
    mock_db = _make_mock_db()
    with patch.object(app_module, "db", mock_db):
        with TestClient(app) as client:
            resp = client.post(
                "/api/feedback",
                json={
                    "category": "feature",
                    "comment": "Make this clearer",
                    "page_url": "https://example.test/#companies",
                    "route": "#companies",
                    "element_metadata": {"tag_name": "button"},
                    "diagnostics": {"browser": {"name": "Chrome"}},
                },
                headers=_AUTH_HEADER,
            )

    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    assert body["id"]
    payload = mock_db.create_feedback_item.call_args.args[0]
    assert payload["project_key"] == "deal-intelligence"
    assert payload["surface"] == "dealintel"
    assert payload["environment"] == "staging"
    assert payload["user_id"] == _FAKE_USER_ID
    assert payload["user_email"] == "jane@rockawayx.com"
    assert payload["user_role"] == "vc"
    assert payload["user_display_name"] == "Jane Investor"
    assert payload["category"] == "other"
    assert payload["comment"] == "Make this clearer"
    assert payload["element_metadata"] == {"tag_name": "button"}
    assert payload["diagnostics"] == {"browser": {"name": "Chrome"}}


def test_feedback_accepts_supabase_user_without_profile():
    import web.app as app_module

    mock_db = _make_mock_db(profile=None)
    mock_db.get_user_profile.return_value = None
    with patch.object(app_module, "db", mock_db):
        with TestClient(app) as client:
            resp = client.post(
                "/api/feedback",
                json={"category": "bug", "comment": "URL mode is missing a toggle"},
                headers=_AUTH_HEADER,
            )

    assert resp.status_code == 201
    payload = mock_db.create_feedback_item.call_args.args[0]
    assert payload["user_id"] == _FAKE_USER_ID
    assert payload["user_email"] == "jane@rockawayx.com"
    assert payload["user_role"] == "authenticated"
    assert payload["user_display_name"] is None


def test_feedback_uploads_webp_screenshot_and_stores_metadata():
    import web.app as app_module

    mock_db = _make_mock_db()
    with patch.object(app_module, "db", mock_db):
        with TestClient(app) as client:
            resp = client.post(
                "/api/feedback",
                json={
                    "category": "bug",
                    "comment": "Panel overlaps chart",
                    "screenshot": {
                        "content_type": "image/webp",
                        "data_base64": base64.b64encode(b"webp-bytes").decode("ascii"),
                    },
                },
                headers=_AUTH_HEADER,
            )

    assert resp.status_code == 201
    mock_db.upload_feedback_screenshot.assert_called_once()
    _, content_type, screenshot_bytes = mock_db.upload_feedback_screenshot.call_args.args
    assert content_type == "image/webp"
    assert screenshot_bytes == b"webp-bytes"
    payload = mock_db.create_feedback_item.call_args.args[0]
    assert payload["screenshot_storage_path"] == "feedback/screenshots/fixed.webp"
    assert payload["screenshot_content_type"] == "image/webp"
    assert payload["screenshot_size_bytes"] == len(b"webp-bytes")


@pytest.mark.parametrize(
    ("screenshot", "detail", "status"),
    [
        ("not-an-object", "screenshot must be an object", 400),
        ({"content_type": "image/png", "data_base64": "AAAA"}, "unsupported screenshot content type", 400),
        ({"content_type": "image/webp", "data_base64": "not base64"}, "screenshot data_base64 is invalid", 400),
    ],
)
def test_feedback_rejects_invalid_screenshot_payloads(screenshot, detail, status):
    import web.app as app_module

    mock_db = _make_mock_db()
    with patch.object(app_module, "db", mock_db):
        with TestClient(app) as client:
            resp = client.post(
                "/api/feedback",
                json={"comment": "Screenshot issue", "screenshot": screenshot},
                headers=_AUTH_HEADER,
            )

    assert resp.status_code == status
    assert resp.json()["detail"] == detail
    mock_db.create_feedback_item.assert_not_called()


def test_feedback_rejects_oversized_screenshot(monkeypatch):
    monkeypatch.setattr(real_db, "FEEDBACK_MAX_SCREENSHOT_BYTES", 4)
    with pytest.raises(real_db.FeedbackScreenshotError) as exc:
        real_db.decode_feedback_screenshot({
            "content_type": "image/webp",
            "data_base64": base64.b64encode(b"12345").decode("ascii"),
        })

    assert str(exc.value) == "screenshot is too large"
    assert exc.value.status_code == 413


def test_feedback_screenshot_upload_failure_returns_502_without_insert():
    import web.app as app_module

    mock_db = _make_mock_db()
    mock_db.upload_feedback_screenshot.return_value = None
    with patch.object(app_module, "db", mock_db):
        with TestClient(app) as client:
            resp = client.post(
                "/api/feedback",
                json={
                    "comment": "Upload should fail",
                    "screenshot": {
                        "content_type": "image/webp",
                        "data_base64": base64.b64encode(b"webp-bytes").decode("ascii"),
                    },
                },
                headers=_AUTH_HEADER,
            )

    assert resp.status_code == 502
    assert resp.json()["detail"] == "screenshot upload failed"
    mock_db.create_feedback_item.assert_not_called()
