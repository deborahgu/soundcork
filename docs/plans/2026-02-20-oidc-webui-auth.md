# OIDC WebUI Authentication

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the WebUI's password-based login with OpenID Connect (OIDC) authentication via any compliant provider (Authentik, Keycloak, Auth0, etc.), while keeping password login as a fallback when OIDC is not configured.

**Architecture:** Add `authlib` as the OIDC client library. New `/auth/login` and `/auth/callback` routes handle the authorization code flow with PKCE. When OIDC settings are present, the login page shows an SSO button that redirects through the provider. When OIDC is not configured, the existing username/password form is shown. Sessions are created in the same `SessionStore` regardless of login method — everything downstream (middleware, CSRF, cookies) is unchanged.

**Tech Stack:** `authlib[httpx]` (OIDC client with async httpx backend), existing FastAPI middleware, existing `SessionStore`.

---

## Design Decisions

1. **Provider-agnostic OIDC** — Only needs `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`. Endpoints auto-discovered from `.well-known/openid-configuration`.
2. **Opt-in via config** — When all three OIDC settings are set, OIDC is enabled. When any is empty, falls back to password login. No code changes needed to switch.
3. **WebUI only** — `/mgmt/*` keeps HTTP Basic Auth. Speaker endpoints keep IP allowlist. OIDC only replaces how WebUI sessions are created.
4. **In-memory sessions** — Same as current. On restart, users re-authenticate (seamless with implicit consent flow — zero clicks if already logged in to the provider).
5. **SoundCork-only logout** — Clears the local session cookie. Does not log out of the SSO provider.
6. **PKCE** — Always used (code_verifier/code_challenge), even though client_secret is also sent. Defense in depth.

## Auth Flow

```
Browser → GET /webui/ → no session → redirect to /auth/login
  → /auth/login generates state + PKCE, redirects to provider
  → User authenticates at provider (or is already logged in)
  → Provider redirects to /auth/callback?code=...&state=...
  → /auth/callback exchanges code for tokens via authlib
  → Validates ID token (signature, issuer, audience, expiry)
  → Creates session in SessionStore (same as password login)
  → Sets webui_session cookie
  → Redirects to /webui/
```

## Config

```
OIDC_ISSUER_URL=https://authentik.example.com/application/o/soundcork/
OIDC_CLIENT_ID=soundcork
OIDC_CLIENT_SECRET=<secret>
```

## Files Changed

| File | Change |
|------|--------|
| `soundcork/config.py` | Add 3 OIDC settings |
| `soundcork/oidc.py` | New: OIDC router (`/auth/login`, `/auth/callback`), authlib client setup |
| `soundcork/main.py` | Mount OIDC router, add `/auth/*` to middleware exemptions |
| `soundcork/webui/auth.py` | Add `/auth/login`, `/auth/callback` to public paths |
| `soundcork/webui/routes.py` | Expose `oidcEnabled` in `/webui/api/config` |
| `soundcork/webui/static/login.html` | Conditional SSO button vs password form |
| `requirements.txt` | Add `authlib` |
| `tests/test_oidc_auth.py` | New: OIDC flow tests (mocked provider) |
| `tests/test_webui_auth.py` | Verify existing password auth still works when OIDC disabled |

---

## Implementation Plan

### Task 1: Add authlib dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add authlib to requirements.txt**

Add `authlib==1.6.0` to `requirements.txt`.

**Step 2: Install and verify**

Run: `pip install -r requirements.txt`
Expected: authlib installs successfully.

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add authlib for OIDC authentication"
```

---

### Task 2: Add OIDC config settings

**Files:**
- Modify: `soundcork/config.py`
- Test: `tests/test_oidc_auth.py` (create)

**Step 1: Write the failing test**

Create `tests/test_oidc_auth.py`:

```python
"""Tests for OIDC authentication."""

from unittest.mock import patch

from soundcork.config import Settings


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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oidc_auth.py -v`
Expected: FAIL — `oidc_issuer_url` not found on Settings.

**Step 3: Add OIDC settings to config.py**

Add to `soundcork/config.py` in the `Settings` class:

```python
    # OIDC authentication (optional — when all three are set, OIDC is enabled)
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer_url and self.oidc_client_id and self.oidc_client_secret)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oidc_auth.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add soundcork/config.py tests/test_oidc_auth.py
git commit -m "feat(auth): add OIDC config settings with oidc_enabled property"
```

---

### Task 3: Create OIDC router with /auth/login and /auth/callback

**Files:**
- Create: `soundcork/oidc.py`
- Modify: `tests/test_oidc_auth.py`

**Step 1: Write the failing tests**

Append to `tests/test_oidc_auth.py`:

```python
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient


def _make_allowlist():
    from soundcork.speaker_allowlist import SpeakerAllowlist
    ds = MagicMock()
    ds.list_accounts.return_value = []
    ds.list_devices.return_value = []
    return SpeakerAllowlist(ds)


@pytest.fixture
def oidc_client():
    """Client with OIDC enabled."""
    import soundcork.main as main_mod
    original = main_mod._speaker_allowlist
    main_mod._speaker_allowlist = _make_allowlist()
    with patch.object(main_mod.settings, "oidc_issuer_url", "https://auth.example.com/app/soundcork/"):
        with patch.object(main_mod.settings, "oidc_client_id", "soundcork"):
            with patch.object(main_mod.settings, "oidc_client_secret", "test-secret"):
                yield TestClient(main_mod.app)
    main_mod._speaker_allowlist = original


class TestOIDCLoginRedirect:
    def test_auth_login_redirects_to_provider(self, oidc_client):
        """GET /auth/login should redirect to the OIDC provider."""
        resp = oidc_client.get("/auth/login", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "auth.example.com" in location
        assert "client_id=soundcork" in location
        assert "response_type=code" in location

    def test_auth_callback_without_code_returns_error(self, oidc_client):
        """GET /auth/callback without a code should return an error."""
        resp = oidc_client.get("/auth/callback", follow_redirects=False)
        assert resp.status_code in (400, 302)  # error or redirect to login
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oidc_auth.py::TestOIDCLoginRedirect -v`
Expected: FAIL — `/auth/login` returns 404.

**Step 3: Create soundcork/oidc.py**

```python
"""OIDC authentication routes (/auth/login, /auth/callback)."""

import logging
import secrets

from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from soundcork.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory store for OIDC state parameters (state -> code_verifier mapping).
# Same lifecycle as the session store — lost on restart, user just re-authenticates.
_pending_flows: dict[str, str] = {}


def _get_oidc_client(settings: Settings) -> AsyncOAuth2Client:
    """Create an authlib OAuth2 client configured from settings."""
    return AsyncOAuth2Client(
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        scope="openid email profile",
        code_challenge_method="S256",
    )


async def _discover_endpoints(settings: Settings) -> dict:
    """Fetch OIDC discovery document."""
    import httpx

    url = settings.oidc_issuer_url.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        return resp.json()


@router.get("/login")
async def auth_login(request: Request):
    """Redirect to the OIDC provider for authentication."""
    settings = Settings()
    if not settings.oidc_enabled:
        return RedirectResponse(url="/webui/login", status_code=302)

    try:
        discovery = await _discover_endpoints(settings)
    except Exception as e:
        logger.error("OIDC discovery failed: %s", e)
        return JSONResponse({"detail": "OIDC provider unreachable"}, status_code=502)

    client = _get_oidc_client(settings)
    callback_url = f"{settings.base_url}/auth/callback"

    uri, state = client.create_authorization_url(
        discovery["authorization_endpoint"],
        redirect_uri=callback_url,
    )

    # Store code_verifier for the callback (keyed by state)
    _pending_flows[state] = client.session_state.get("code_verifier", "")

    return RedirectResponse(url=uri, status_code=302)


@router.get("/callback")
async def auth_callback(request: Request):
    """Handle the OIDC provider callback and create a session."""
    settings = Settings()
    if not settings.oidc_enabled:
        return RedirectResponse(url="/webui/login", status_code=302)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        logger.warning("OIDC callback error: %s - %s", error, request.query_params.get("error_description", ""))
        return RedirectResponse(url="/webui/login", status_code=302)

    if not code or not state:
        return RedirectResponse(url="/webui/login", status_code=302)

    code_verifier = _pending_flows.pop(state, None)
    if code_verifier is None:
        logger.warning("OIDC callback with unknown state: %s", state)
        return RedirectResponse(url="/webui/login", status_code=302)

    try:
        discovery = await _discover_endpoints(settings)
        client = _get_oidc_client(settings)
        callback_url = f"{settings.base_url}/auth/callback"

        token = await client.fetch_token(
            discovery["token_endpoint"],
            code=code,
            redirect_uri=callback_url,
            code_verifier=code_verifier,
        )
    except Exception as e:
        logger.error("OIDC token exchange failed: %s", e)
        return RedirectResponse(url="/webui/login", status_code=302)

    # Extract user info from the ID token (already validated by authlib)
    id_token = token.get("userinfo") or {}
    email = id_token.get("email", "oidc-user")
    logger.info("OIDC login successful for %s", email)

    # Create session using the same session store as password login
    from soundcork.webui.routes import _session_store, _SESSION_COOKIE

    session_id, csrf_token = _session_store.create()

    # Set session cookie and redirect to WebUI
    # Also store CSRF token in a JS-readable cookie so the frontend can pick it up
    response = RedirectResponse(url="/webui/", status_code=302)
    response.set_cookie(
        key=_SESSION_COOKIE,
        value=session_id,
        httponly=True,
        samesite="lax",
        path="/webui",
        secure=str(request.url).startswith("https"),
    )
    # Store CSRF token in a non-httponly cookie so JS can read it
    response.set_cookie(
        key="webui_csrf",
        value=csrf_token,
        httponly=False,
        samesite="lax",
        path="/webui",
        secure=str(request.url).startswith("https"),
    )
    return response
```

**Step 4: Mount the router in main.py**

In `soundcork/main.py`, after the webui router mount, add:

```python
from soundcork.oidc import router as oidc_router
app.include_router(oidc_router)
```

And add `"/auth"` to `_EXEMPT_PREFIXES` so the speaker IP restriction middleware doesn't block it.

**Step 5: Run tests**

Run: `pytest tests/test_oidc_auth.py -v`

**Step 6: Commit**

```bash
git add soundcork/oidc.py soundcork/main.py tests/test_oidc_auth.py
git commit -m "feat(auth): add OIDC login and callback routes with authlib"
```

---

### Task 4: Update WebUI auth to recognize /auth/* as public paths

**Files:**
- Modify: `soundcork/webui/auth.py`
- Modify: `soundcork/main.py` (middleware exemption)

**Step 1: Add /auth paths to public paths and middleware exemptions**

In `soundcork/webui/auth.py`, the `WEBUI_PUBLIC_PATHS` and `WEBUI_PUBLIC_PREFIXES` don't need changes because `/auth/*` is NOT under `/webui/` — the webui middleware already ignores non-`/webui` paths.

In `soundcork/main.py`, add `"/auth"` to `_EXEMPT_PREFIXES`:

```python
_EXEMPT_PREFIXES = ("/webui", "/mgmt", "/docs", "/openapi.json", "/auth")
```

**Step 2: Run existing tests to verify nothing breaks**

Run: `pytest tests/ -v`

**Step 3: Commit**

```bash
git add soundcork/main.py
git commit -m "fix(auth): exempt /auth/* from speaker IP restriction middleware"
```

---

### Task 5: Expose oidcEnabled in WebUI config endpoint

**Files:**
- Modify: `soundcork/webui/routes.py`
- Modify: `tests/test_webui_auth.py`

**Step 1: Write the failing test**

Add to `tests/test_webui_auth.py`:

```python
class TestWebUIConfig:
    def test_config_includes_oidc_enabled(self, client):
        _login(client)
        with patch("soundcork.webui.routes._settings") as mock_settings:
            mock_settings.base_url = ""
            mock_settings.spotify_client_id = ""
            mock_settings.oidc_enabled = False
            resp = client.get("/webui/api/config")
        assert resp.status_code == 200
        assert "oidcEnabled" in resp.json()
        assert resp.json()["oidcEnabled"] is False
```

**Step 2: Add oidcEnabled to the config endpoint**

In `soundcork/webui/routes.py`, modify `webui_config`:

```python
@router.get("/api/config")
async def webui_config():
    return {
        "baseUrl": _settings.base_url,
        "hasSpotify": bool(_settings.spotify_client_id),
        "oidcEnabled": _settings.oidc_enabled,
    }
```

**Step 3: Run tests**

Run: `pytest tests/test_webui_auth.py::TestWebUIConfig -v`

**Step 4: Commit**

```bash
git add soundcork/webui/routes.py tests/test_webui_auth.py
git commit -m "feat(webui): expose oidcEnabled in config endpoint"
```

---

### Task 6: Update login page with conditional SSO button

**Files:**
- Modify: `soundcork/webui/static/login.html`

**Step 1: Update login.html**

Add a script that fetches `/webui/api/config` (public when not logged in — needs a small change) or check config on page load. Since the login page is public but `/webui/api/config` requires auth, we need a different approach: make the login page check for OIDC by hitting a new public endpoint, or embed the info.

Simpler: add a small public endpoint `/auth/config` that returns `{"oidcEnabled": true/false}`:

In `soundcork/oidc.py`, add:

```python
@router.get("/config")
async def auth_config():
    settings = Settings()
    return {"oidcEnabled": settings.oidc_enabled}
```

Then update `login.html` to:
1. On load, fetch `/auth/config`
2. If `oidcEnabled`, show "Sign in with SSO" button, hide password form
3. If not, show the existing password form

Also update the frontend `app.js` to read the CSRF token from the `webui_csrf` cookie (for OIDC logins, since there's no JSON response to read it from).

**Step 2: Run manual test / verify page loads**

**Step 3: Commit**

```bash
git add soundcork/oidc.py soundcork/webui/static/login.html soundcork/webui/static/app.js
git commit -m "feat(webui): conditional SSO button on login page"
```

---

### Task 7: Update app.js to read CSRF token from cookie (OIDC flow)

**Files:**
- Modify: `soundcork/webui/static/app.js`

**Step 1: Update CSRF token reading**

The OIDC callback sets a `webui_csrf` cookie. The password login returns CSRF in JSON (stored in `sessionStorage`). Update the fetch wrapper to check both:

```javascript
function getCsrfToken() {
  // First check sessionStorage (password login)
  const stored = sessionStorage.getItem('csrf_token');
  if (stored) return stored;
  // Then check cookie (OIDC login)
  const match = document.cookie.match(/webui_csrf=([^;]+)/);
  if (match) {
    // Move to sessionStorage for consistency
    sessionStorage.setItem('csrf_token', match[1]);
    return match[1];
  }
  return null;
}
```

**Step 2: Commit**

```bash
git add soundcork/webui/static/app.js
git commit -m "fix(webui): read CSRF token from cookie for OIDC login flow"
```

---

### Task 8: Add integration tests for full OIDC flow

**Files:**
- Modify: `tests/test_oidc_auth.py`

**Step 1: Add tests for the complete flow with mocked provider**

Test scenarios:
- `/auth/login` when OIDC disabled redirects to `/webui/login`
- `/auth/login` when OIDC enabled redirects to provider
- `/auth/callback` with valid code creates session and redirects to `/webui/`
- `/auth/callback` with invalid state redirects to login
- `/auth/callback` with error param redirects to login
- `/auth/config` returns correct `oidcEnabled` value
- Existing password login still works when OIDC is enabled
- All existing webui auth tests still pass

**Step 2: Run full test suite**

Run: `pytest tests/ -v`

**Step 3: Commit**

```bash
git add tests/test_oidc_auth.py
git commit -m "test(auth): add OIDC authentication integration tests"
```

---

### Task 9: Verify and final commit

**Step 1: Run full test suite**

Run: `pytest tests/ -v`

**Step 2: Run linter**

Run: `ruff check soundcork/ tests/`

**Step 3: Manual verification checklist**
- [ ] OIDC disabled: login page shows password form, login works
- [ ] OIDC enabled: login page shows SSO button, redirects to provider
- [ ] After OIDC login: session cookie set, CSRF works, WebUI accessible
- [ ] Logout: session cleared, redirect to login page
- [ ] Speaker endpoints: unaffected by OIDC changes
- [ ] Management API: unaffected by OIDC changes
