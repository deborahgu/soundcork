"""OIDC authentication routes (/auth/login, /auth/callback, /auth/config)."""

import logging
import secrets

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from soundcork.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory store for OIDC state parameters (state -> code_verifier mapping).
# Same lifecycle as the session store — lost on restart, user just re-authenticates.
_pending_flows: dict[str, str] = {}


async def _discover_endpoints(settings: Settings) -> dict:
    """Fetch OIDC discovery document from the provider."""
    url = settings.oidc_issuer_url.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        return resp.json()


@router.get("/config")
async def auth_config():
    """Return OIDC status (public endpoint, no auth required)."""
    settings = Settings()
    return {"oidcEnabled": settings.oidc_enabled}


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

    callback_url = f"{settings.base_url}/auth/callback"

    # Generate PKCE code_verifier (43-128 chars, URL-safe)
    code_verifier = secrets.token_urlsafe(48)

    client = AsyncOAuth2Client(
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        scope="openid email profile",
        redirect_uri=callback_url,
        code_challenge_method="S256",
    )

    uri, state = client.create_authorization_url(
        discovery["authorization_endpoint"],
        code_verifier=code_verifier,
    )

    # Store code_verifier for the callback (keyed by state)
    _pending_flows[state] = code_verifier

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
        logger.warning(
            "OIDC callback error: %s - %s",
            error,
            request.query_params.get("error_description", ""),
        )
        return RedirectResponse(url="/webui/login", status_code=302)

    if not code or not state:
        return RedirectResponse(url="/webui/login", status_code=302)

    code_verifier = _pending_flows.pop(state, None)
    if code_verifier is None:
        logger.warning("OIDC callback with unknown state: %s", state)
        return RedirectResponse(url="/webui/login", status_code=302)

    try:
        discovery = await _discover_endpoints(settings)
        callback_url = f"{settings.base_url}/auth/callback"

        client = AsyncOAuth2Client(
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            redirect_uri=callback_url,
        )

        token = await client.fetch_token(
            discovery["token_endpoint"],
            code=code,
            code_verifier=code_verifier,
        )
    except Exception as e:
        logger.error("OIDC token exchange failed: %s", e)
        return RedirectResponse(url="/webui/login", status_code=302)

    # Extract user info from the ID token
    id_token = token.get("userinfo") or {}
    email = id_token.get("email", "oidc-user")
    logger.info("OIDC login successful for %s", email)

    # Create session using the same session store as password login
    from soundcork.webui.routes import _SESSION_COOKIE, _session_store

    session_id, csrf_token = _session_store.create()

    # Set session cookie and redirect to WebUI
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
