"""WebUI session authentication."""

import secrets
from dataclasses import dataclass

from soundcork.config import Settings


@dataclass
class _Session:
    csrf_token: str


class SessionStore:
    """In-memory session store. Sessions lost on restart (user re-logs in)."""

    def __init__(self):
        self._sessions: dict[str, _Session] = {}

    def create(self) -> tuple[str, str]:
        """Create a new session. Returns (session_id, csrf_token)."""
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        self._sessions[session_id] = _Session(csrf_token=csrf_token)
        return session_id, csrf_token

    def validate(self, session_id: str) -> str | None:
        """Return the CSRF token if session is valid, else None."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return session.csrf_token

    def destroy(self, session_id: str) -> None:
        """Remove a session."""
        self._sessions.pop(session_id, None)


# Paths under /webui that don't require authentication
WEBUI_PUBLIC_PATHS = frozenset({"/webui/login", "/webui/api/login"})
WEBUI_PUBLIC_PREFIXES = ("/webui/static/",)


def is_webui_path_public(path: str) -> bool:
    """Check if a webui path is accessible without authentication."""
    if path in WEBUI_PUBLIC_PATHS:
        return True
    return any(path.startswith(p) for p in WEBUI_PUBLIC_PREFIXES)


def verify_login(username: str, password: str) -> bool:
    """Verify login credentials against mgmt settings (timing-safe)."""
    s = Settings()
    username_ok = secrets.compare_digest(
        username.encode("utf-8"),
        s.mgmt_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        password.encode("utf-8"),
        s.mgmt_password.encode("utf-8"),
    )
    return username_ok and password_ok
