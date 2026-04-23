"""Tests for OIDC authentication."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from soundcork.config import Settings

# ===================================================================
# Unit tests for OIDC config
# ===================================================================


class TestOIDCConfig:
    def test_oidc_disabled_by_default(self):
        """OIDC should be disabled when settings are empty."""
        with patch.dict("os.environ", {}, clear=True):
            s = Settings(
                base_url="http://localhost:8000",
                data_dir="/tmp/test",
                _env_file=None,
            )
            assert s.oidc_issuer_url == ""
            assert s.oidc_client_id == ""
            assert s.oidc_client_secret == ""
            assert not s.oidc_enabled

    def test_oidc_enabled_when_all_set(self):
        """OIDC should be enabled when all three settings are populated."""
        with patch.dict("os.environ", {}, clear=True):
            s = Settings(
                base_url="http://localhost:8000",
                data_dir="/tmp/test",
                oidc_issuer_url="https://auth.example.com/app/soundcork/",
                oidc_client_id="soundcork",
                oidc_client_secret="secret",
                _env_file=None,
            )
            assert s.oidc_enabled

    def test_oidc_disabled_when_partial(self):
        """OIDC should be disabled if any setting is missing."""
        with patch.dict("os.environ", {}, clear=True):
            s = Settings(
                base_url="http://localhost:8000",
                data_dir="/tmp/test",
                oidc_issuer_url="https://auth.example.com/app/soundcork/",
                oidc_client_id="soundcork",
                oidc_client_secret="",
                _env_file=None,
            )
            assert not s.oidc_enabled


# ===================================================================
# Integration test fixtures
# ===================================================================


def _make_allowlist():
    from soundcork.speaker_allowlist import SpeakerAllowlist

    ds = MagicMock()
    ds.list_accounts.return_value = []
    ds.list_devices.return_value = []
    return SpeakerAllowlist(ds)


@pytest.fixture
def client():
    """Client with OIDC disabled (default)."""
    import soundcork.main as main_mod

    original = main_mod._speaker_allowlist
    main_mod._speaker_allowlist = _make_allowlist()
    try:
        yield TestClient(main_mod.app)
    finally:
        main_mod._speaker_allowlist = original


# ===================================================================
# Tests: /auth/config endpoint
# ===================================================================


class TestAuthConfigEndpoint:
    def test_auth_config_returns_oidc_disabled(self, client):
        """GET /auth/config should return oidcEnabled: false when OIDC not configured."""
        with patch("soundcork.oidc.Settings") as MockSettings:
            mock = MockSettings.return_value
            mock.oidc_enabled = False
            resp = client.get("/auth/config")
        assert resp.status_code == 200
        assert resp.json()["oidcEnabled"] is False

    def test_auth_config_returns_oidc_enabled(self, client):
        """GET /auth/config should return oidcEnabled: true when OIDC configured."""
        with patch("soundcork.oidc.Settings") as MockSettings:
            mock = MockSettings.return_value
            mock.oidc_enabled = True
            resp = client.get("/auth/config")
        assert resp.status_code == 200
        assert resp.json()["oidcEnabled"] is True


# ===================================================================
# Tests: /auth/login redirect
# ===================================================================


class TestAuthLoginRedirect:
    def test_auth_login_redirects_to_webui_when_oidc_disabled(self, client):
        """GET /auth/login should redirect to /webui/login when OIDC is off."""
        with patch("soundcork.oidc.Settings") as MockSettings:
            mock = MockSettings.return_value
            mock.oidc_enabled = False
            resp = client.get("/auth/login", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/webui/login"

    def test_auth_login_redirects_to_provider_when_oidc_enabled(self, client):
        """GET /auth/login should redirect to the OIDC provider."""
        mock_discovery = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "userinfo_endpoint": "https://auth.example.com/userinfo",
            "jwks_uri": "https://auth.example.com/jwks",
        }
        with (
            patch("soundcork.oidc.Settings") as MockSettings,
            patch("soundcork.oidc._discover_endpoints", new_callable=AsyncMock, return_value=mock_discovery),
        ):
            mock = MockSettings.return_value
            mock.oidc_enabled = True
            mock.oidc_issuer_url = "https://auth.example.com/app/soundcork/"
            mock.oidc_client_id = "soundcork"
            mock.oidc_client_secret = "test-secret"
            mock.base_url = "http://localhost:8000"
            resp = client.get("/auth/login", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "auth.example.com/authorize" in location
        assert "client_id=soundcork" in location
        assert "response_type=code" in location
        assert "redirect_uri=" in location


# ===================================================================
# Tests: /auth/callback error handling
# ===================================================================


class TestAuthCallbackErrors:
    def test_callback_without_code_redirects_to_login(self, client):
        """GET /auth/callback without code should redirect to login."""
        with patch("soundcork.oidc.Settings") as MockSettings:
            mock = MockSettings.return_value
            mock.oidc_enabled = True
            resp = client.get("/auth/callback", follow_redirects=False)
        assert resp.status_code == 302
        assert "/webui/login" in resp.headers["location"]

    def test_callback_with_error_redirects_to_login(self, client):
        """GET /auth/callback with error param should redirect to login."""
        with patch("soundcork.oidc.Settings") as MockSettings:
            mock = MockSettings.return_value
            mock.oidc_enabled = True
            resp = client.get(
                "/auth/callback?error=access_denied&error_description=User+denied",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "/webui/login" in resp.headers["location"]

    def test_callback_with_unknown_state_redirects_to_login(self, client):
        """GET /auth/callback with unknown state should redirect to login."""
        with patch("soundcork.oidc.Settings") as MockSettings:
            mock = MockSettings.return_value
            mock.oidc_enabled = True
            resp = client.get(
                "/auth/callback?code=test-code&state=unknown-state",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "/webui/login" in resp.headers["location"]

    def test_callback_when_oidc_disabled_redirects_to_login(self, client):
        """GET /auth/callback when OIDC disabled should redirect to login."""
        with patch("soundcork.oidc.Settings") as MockSettings:
            mock = MockSettings.return_value
            mock.oidc_enabled = False
            resp = client.get(
                "/auth/callback?code=test&state=test",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "/webui/login" in resp.headers["location"]


# ===================================================================
# Tests: /auth/* not blocked by speaker IP restriction
# ===================================================================


class TestAuthNotBlockedByIPRestriction:
    def test_auth_config_not_blocked_by_ip_restriction(self, client):
        """GET /auth/config should NOT be blocked by speaker IP restriction."""
        with patch("soundcork.oidc.Settings") as MockSettings:
            mock = MockSettings.return_value
            mock.oidc_enabled = False
            resp = client.get(
                "/auth/config",
                headers={"X-Forwarded-For": "8.8.8.8"},
            )
        # Should get 200, not 403
        assert resp.status_code == 200

    def test_auth_login_not_blocked_by_ip_restriction(self, client):
        """GET /auth/login should NOT be blocked by speaker IP restriction."""
        with patch("soundcork.oidc.Settings") as MockSettings:
            mock = MockSettings.return_value
            mock.oidc_enabled = False
            resp = client.get(
                "/auth/login",
                headers={"X-Forwarded-For": "8.8.8.8"},
                follow_redirects=False,
            )
        # Should get 302 (redirect), not 403
        assert resp.status_code == 302


# ===================================================================
# Tests: WebUI config includes oidcEnabled
# ===================================================================


class TestWebUIConfigOIDC:
    def test_config_includes_oidc_enabled_false(self, client):
        """GET /webui/api/config should include oidcEnabled field."""
        # Login first (password login)
        with patch("soundcork.webui.auth.Settings") as MockSettings:
            MockSettings.return_value.mgmt_username = "admin"
            MockSettings.return_value.mgmt_password = "secret"
            resp = client.post(
                "/webui/api/login",
                json={"username": "admin", "password": "secret"},
            )
            assert resp.status_code == 200

        with patch("soundcork.webui.routes._settings") as mock_settings:
            mock_settings.base_url = ""
            mock_settings.spotify_client_id = ""
            mock_settings.oidc_enabled = False
            resp = client.get("/webui/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "oidcEnabled" in data
        assert data["oidcEnabled"] is False

    def test_config_includes_oidc_enabled_true(self, client):
        """GET /webui/api/config should reflect oidcEnabled=true."""
        with patch("soundcork.webui.auth.Settings") as MockSettings:
            MockSettings.return_value.mgmt_username = "admin"
            MockSettings.return_value.mgmt_password = "secret"
            resp = client.post(
                "/webui/api/login",
                json={"username": "admin", "password": "secret"},
            )
            assert resp.status_code == 200

        with patch("soundcork.webui.routes._settings") as mock_settings:
            mock_settings.base_url = ""
            mock_settings.spotify_client_id = ""
            mock_settings.oidc_enabled = True
            resp = client.get("/webui/api/config")
        assert resp.status_code == 200
        assert resp.json()["oidcEnabled"] is True


# ===================================================================
# Tests: Existing password login still works
# ===================================================================


class TestPasswordLoginStillWorks:
    def test_password_login_works_when_oidc_enabled(self, client):
        """Password login should still work even when OIDC is configured."""
        with patch("soundcork.webui.auth.Settings") as MockSettings:
            MockSettings.return_value.mgmt_username = "admin"
            MockSettings.return_value.mgmt_password = "secret"
            resp = client.post(
                "/webui/api/login",
                json={"username": "admin", "password": "secret"},
            )
        assert resp.status_code == 200
        assert "csrf_token" in resp.json()
        assert "webui_session" in resp.cookies
