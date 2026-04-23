"""Tests for webui session auth."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from soundcork.speaker_allowlist import SpeakerAllowlist
from soundcork.webui.auth import SessionStore, verify_login

# ===================================================================
# Unit tests for SessionStore
# ===================================================================


class TestSessionStore:
    def test_create_session_returns_id_and_csrf(self):
        store = SessionStore()
        session_id, csrf_token = store.create()
        assert isinstance(session_id, str)
        assert isinstance(csrf_token, str)
        assert len(session_id) >= 32
        assert len(csrf_token) >= 32

    def test_validate_returns_csrf_for_valid_session(self):
        store = SessionStore()
        session_id, csrf_token = store.create()
        result = store.validate(session_id)
        assert result == csrf_token

    def test_validate_returns_none_for_unknown_session(self):
        store = SessionStore()
        assert store.validate("nonexistent") is None

    def test_destroy_removes_session(self):
        store = SessionStore()
        session_id, csrf_token = store.create()
        store.destroy(session_id)
        assert store.validate(session_id) is None

    def test_destroy_nonexistent_is_noop(self):
        store = SessionStore()
        store.destroy("nonexistent")  # should not raise


# ===================================================================
# Unit tests for verify_login
# ===================================================================


class TestVerifyLogin:
    @patch("soundcork.webui.auth.Settings")
    def test_valid_credentials(self, MockSettings):
        MockSettings.return_value.mgmt_username = "admin"
        MockSettings.return_value.mgmt_password = "secret"
        assert verify_login("admin", "secret") is True

    @patch("soundcork.webui.auth.Settings")
    def test_wrong_password(self, MockSettings):
        MockSettings.return_value.mgmt_username = "admin"
        MockSettings.return_value.mgmt_password = "secret"
        assert verify_login("admin", "wrong") is False

    @patch("soundcork.webui.auth.Settings")
    def test_wrong_username(self, MockSettings):
        MockSettings.return_value.mgmt_username = "admin"
        MockSettings.return_value.mgmt_password = "secret"
        assert verify_login("wrong", "secret") is False

    @patch("soundcork.webui.auth.Settings")
    def test_empty_credentials(self, MockSettings):
        MockSettings.return_value.mgmt_username = "admin"
        MockSettings.return_value.mgmt_password = "secret"
        assert verify_login("", "") is False


# ===================================================================
# Integration test fixtures
# ===================================================================


def _make_allowlist() -> SpeakerAllowlist:
    """Minimal allowlist for webui tests (no speakers needed)."""
    ds = MagicMock()
    ds.list_accounts.return_value = []
    ds.list_devices.return_value = []
    return SpeakerAllowlist(ds)


@pytest.fixture
def client():
    import soundcork.main as main_mod

    original = main_mod._speaker_allowlist
    main_mod._speaker_allowlist = _make_allowlist()
    try:
        yield TestClient(main_mod.app)
    finally:
        main_mod._speaker_allowlist = original


def _login(client) -> str:
    """Login helper. Returns CSRF token. Modifies client cookies in-place."""
    with patch("soundcork.webui.auth.Settings") as MockSettings:
        MockSettings.return_value.mgmt_username = "admin"
        MockSettings.return_value.mgmt_password = "secret"
        resp = client.post(
            "/webui/api/login",
            json={"username": "admin", "password": "secret"},
        )
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        return resp.json()["csrf_token"]


# ===================================================================
# Integration tests: Login endpoint
# ===================================================================


class TestLoginEndpoint:
    def test_login_success(self, client):
        with patch("soundcork.webui.auth.Settings") as MockSettings:
            MockSettings.return_value.mgmt_username = "admin"
            MockSettings.return_value.mgmt_password = "secret"
            resp = client.post(
                "/webui/api/login",
                json={"username": "admin", "password": "secret"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "csrf_token" in data
        assert "webui_session" in resp.cookies

    def test_login_wrong_password(self, client):
        with patch("soundcork.webui.auth.Settings") as MockSettings:
            MockSettings.return_value.mgmt_username = "admin"
            MockSettings.return_value.mgmt_password = "secret"
            resp = client.post(
                "/webui/api/login",
                json={"username": "admin", "password": "wrong"},
            )
        assert resp.status_code == 401
        assert "webui_session" not in resp.cookies

    def test_login_missing_fields(self, client):
        with patch("soundcork.webui.auth.Settings") as MockSettings:
            MockSettings.return_value.mgmt_username = "admin"
            MockSettings.return_value.mgmt_password = "secret"
            resp = client.post("/webui/api/login", json={})
        assert resp.status_code == 401


# ===================================================================
# Integration tests: Logout endpoint
# ===================================================================


class TestLogoutEndpoint:
    def test_logout_clears_session(self, client):
        csrf = _login(client)
        # Logout
        resp = client.post(
            "/webui/api/logout",
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200
        # Verify session is gone — next API call should be 401
        resp2 = client.get("/webui/api/config")
        assert resp2.status_code == 401


# ===================================================================
# Integration tests: Auth middleware
# ===================================================================


class TestAuthMiddleware:
    """All /webui/* requests (except login) require a valid session."""

    def test_unauthenticated_api_returns_401(self, client):
        resp = client.get("/webui/api/config")
        assert resp.status_code == 401

    def test_unauthenticated_speakers_returns_401(self, client):
        resp = client.get("/webui/api/speakers")
        assert resp.status_code == 401

    def test_unauthenticated_index_redirects_to_login(self, client):
        resp = client.get("/webui/", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/webui/login"

    def test_login_page_accessible_without_session(self, client):
        resp = client.get("/webui/login")
        assert resp.status_code == 200

    def test_login_endpoint_accessible_without_session(self, client):
        # Should get 401 (bad creds), not blocked by middleware
        with patch("soundcork.webui.auth.Settings") as MockSettings:
            MockSettings.return_value.mgmt_username = "admin"
            MockSettings.return_value.mgmt_password = "secret"
            resp = client.post("/webui/api/login", json={"username": "", "password": ""})
        assert resp.status_code == 401

    def test_static_css_accessible_without_session(self, client):
        resp = client.get("/webui/static/style.css")
        assert resp.status_code == 200

    def test_authenticated_api_returns_200(self, client):
        _login(client)
        with patch("soundcork.webui.routes._settings") as mock_settings:
            mock_settings.base_url = ""
            mock_settings.spotify_client_id = ""
            resp = client.get("/webui/api/config")
        assert resp.status_code == 200

    def test_invalid_session_cookie_returns_401(self, client):
        client.cookies.set("webui_session", "bogus", domain="testserver", path="/webui")
        resp = client.get("/webui/api/config")
        assert resp.status_code == 401

    def test_bose_endpoints_unaffected(self, client):
        """Auth middleware must NOT interfere with Bose protocol endpoints."""
        resp = client.get(
            "/marge/streaming/sourceproviders",
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        # Loopback is always allowed by speaker IP middleware
        assert resp.status_code == 200


# ===================================================================
# Integration tests: CSRF protection
# ===================================================================


class TestCSRFProtection:
    """Mutating requests require a valid X-CSRF-Token header."""

    def test_post_without_csrf_returns_403(self, client):
        _login(client)
        resp = client.post(
            "/webui/api/speakers",
            json={"ipAddress": "1.2.3.4", "name": "Test"},
        )
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["detail"]

    def test_post_with_wrong_csrf_returns_403(self, client):
        _login(client)
        resp = client.post(
            "/webui/api/speakers",
            json={"ipAddress": "1.2.3.4", "name": "Test"},
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert resp.status_code == 403

    def test_post_with_valid_csrf_succeeds(self, client):
        csrf = _login(client)
        with patch("soundcork.webui.routes._settings") as mock_settings:
            mock_settings.data_dir = "/tmp/soundcork-test"
            resp = client.post(
                "/webui/api/speakers",
                json={"ipAddress": "1.2.3.4", "name": "Test"},
                headers={"X-CSRF-Token": csrf},
            )
        # 200 or 409 (if speaker exists from a prior run), but NOT 403
        assert resp.status_code in (200, 409)

    def test_get_does_not_require_csrf(self, client):
        _login(client)
        with patch("soundcork.webui.routes._settings") as mock_settings:
            mock_settings.base_url = ""
            mock_settings.spotify_client_id = ""
            resp = client.get("/webui/api/config")
        assert resp.status_code == 200

    def test_delete_requires_csrf(self, client):
        _login(client)
        resp = client.delete("/webui/api/speakers/1.2.3.4")
        assert resp.status_code == 403

    def test_put_requires_csrf(self, client):
        _login(client)
        resp = client.put(
            "/webui/api/speakers/1.2.3.4",
            json={"name": "Updated"},
        )
        assert resp.status_code == 403
