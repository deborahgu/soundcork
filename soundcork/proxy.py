import json
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from soundcork.config import Settings

logger = logging.getLogger(__name__)

# Bose server mapping (from /opt/Bose/etc/SoundTouchSdkPrivateCfg.xml)
UPSTREAM_MAP: dict[str, str] = {
    "/marge": "https://streaming.bose.com",
    "/bmx": "https://content.api.bose.io",
    "/updates": "https://worldwide.bose.com",
}

# Hop-by-hop headers that must not be forwarded
HOP_BY_HOP = frozenset(
    {
        "host",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "upgrade",
    }
)

# How long (seconds) to wait before retrying an upstream after failure
CIRCUIT_BREAKER_COOLDOWN = 300  # 5 minutes

# Upstream request timeout (seconds) — fail fast to avoid blocking the speaker
UPSTREAM_TIMEOUT = 10.0


class CircuitBreaker:
    """Simple circuit breaker for upstream servers.

    States:
      CLOSED  — upstream healthy, forward requests normally
      OPEN    — upstream failed recently, skip directly to local fallback
      HALF-OPEN — cooldown expired, try one request to probe upstream health
    """

    def __init__(self, cooldown: float = CIRCUIT_BREAKER_COOLDOWN):
        self._cooldown = cooldown
        # upstream_host -> {"open": bool, "last_failure": float, "failures": int}
        self._circuits: dict[str, dict] = {}

    def is_open(self, upstream_base: str) -> bool:
        """Return True if the circuit is open (upstream assumed down)."""
        state = self._circuits.get(upstream_base)
        if state is None or not state["open"]:
            return False
        # Check if cooldown has expired (half-open: allow a probe)
        if time.monotonic() - state["last_failure"] > self._cooldown:
            return False
        return True

    def record_failure(self, upstream_base: str) -> None:
        """Mark an upstream as failed."""
        state = self._circuits.get(upstream_base)
        if state is None:
            self._circuits[upstream_base] = {
                "open": True,
                "last_failure": time.monotonic(),
                "failures": 1,
            }
        else:
            state["open"] = True
            state["last_failure"] = time.monotonic()
            state["failures"] += 1
        logger.warning(
            "CIRCUIT OPEN: %s marked as down (total failures: %d)",
            upstream_base,
            self._circuits[upstream_base]["failures"],
        )

    def record_success(self, upstream_base: str) -> None:
        """Mark an upstream as healthy (close the circuit)."""
        state = self._circuits.get(upstream_base)
        if state is not None and state["open"]:
            logger.info("CIRCUIT CLOSED: %s is back up", upstream_base)
            state["open"] = False
            state["failures"] = 0

    def get_status(self, upstream_base: str) -> str:
        """Return human-readable status for logging."""
        state = self._circuits.get(upstream_base)
        if state is None or not state["open"]:
            return "healthy"
        elapsed = time.monotonic() - state["last_failure"]
        if elapsed > self._cooldown:
            return "half-open (probing)"
        return f"down (failures={state['failures']}, retry in {self._cooldown - elapsed:.0f}s)"


# Singleton circuit breaker shared across requests
_circuit_breaker = CircuitBreaker()


def _match_upstream(path: str) -> tuple[str, str] | None:
    """Return (upstream_base, prefix) if path matches a known Bose prefix."""
    for prefix, upstream in UPSTREAM_MAP.items():
        if path == prefix or path.startswith(prefix + "/"):
            return upstream, prefix
    return None


def _log_exchange(
    log_dir: str,
    method: str,
    path: str,
    query: str,
    req_headers: dict,
    req_body: bytes,
    upstream_url: str,
    status: int,
    resp_headers: dict,
    resp_body: bytes,
    fallback: str | None = None,
) -> None:
    """Append a JSON-lines entry to the traffic log file.

    Args:
        fallback: None if no fallback occurred, otherwise a reason string:
            "circuit_open" — upstream circuit was open, skipped to local
            "upstream_error" — upstream request failed, fell back to local
            "upstream_http_error" — upstream returned 5xx, fell back to local
    """
    os.makedirs(log_dir, exist_ok=True)

    now = datetime.now(timezone.utc)

    # Best-effort decode bodies as text; fall back to repr
    try:
        req_body_str = req_body.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        req_body_str = repr(req_body)

    try:
        resp_body_str = resp_body.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        resp_body_str = repr(resp_body)

    entry = {
        "timestamp": now.isoformat(),
        "request": {
            "method": method,
            "path": path,
            "query": query,
            "headers": req_headers,
            "body": req_body_str,
        },
        "upstream_url": upstream_url,
        "response": {
            "status": status,
            "headers": resp_headers,
            "body": resp_body_str,
        },
    }

    if fallback:
        entry["fallback"] = fallback

    filepath = os.path.join(log_dir, "traffic.jsonl")
    try:
        with open(filepath, "a") as f:
            json.dump(entry, f, default=str)
            f.write("\n")
    except OSError:
        logger.exception("Failed to write traffic log to %s", filepath)


class ProxyMiddleware(BaseHTTPMiddleware):
    """Smart proxy to Bose servers with circuit breaker fallback.

    When SOUNDCORK_MODE=proxy, requests matching known Bose path prefixes
    are forwarded to the real upstream servers. If an upstream is unreachable
    or returns a server error, the request falls back to soundcork's local
    handlers automatically. A circuit breaker tracks upstream health to avoid
    repeated timeouts once a server is confirmed down.
    """

    def __init__(self, app):
        super().__init__(app)
        self._settings = Settings()

    async def dispatch(self, request: Request, call_next):
        if self._settings.soundcork_mode != "proxy":
            return await call_next(request)

        match = _match_upstream(request.url.path)
        if match is None:
            # Not a known Bose prefix — handle locally but still log
            return await self._log_local(request, call_next)

        upstream_base, prefix = match
        return await self._forward_with_fallback(request, call_next, upstream_base, prefix)

    async def _log_local(
        self,
        request: Request,
        call_next,
        fallback: str | None = None,
        upstream_url: str = "local",
    ) -> Response:
        """Pass request to local handler and log the exchange."""
        method = request.method
        path = request.url.path
        query = str(request.url.query)
        req_headers = {k: v for k, v in request.headers.items()}
        req_body = await request.body()

        response = await call_next(request)

        # Read the response body (StreamingResponse requires collecting chunks)
        body_chunks = []
        async for chunk in response.body_iterator:
            body_chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
        resp_body = b"".join(body_chunks)

        resp_headers = dict(response.headers)

        if fallback:
            logger.warning(
                "FALLBACK [%s]: %s %s -> local (was: %s)",
                fallback,
                method,
                path,
                upstream_url,
            )

        _log_exchange(
            log_dir=self._settings.soundcork_log_dir,
            method=method,
            path=path,
            query=query,
            req_headers=req_headers,
            req_body=req_body,
            upstream_url=upstream_url,
            status=response.status_code,
            resp_headers=resp_headers,
            resp_body=resp_body,
            fallback=fallback,
        )

        # Return a new Response since we consumed the body iterator
        return Response(
            content=resp_body,
            status_code=response.status_code,
            headers=resp_headers,
        )

    async def _forward_with_fallback(
        self,
        request: Request,
        call_next,
        upstream_base: str,
        prefix: str,
    ) -> Response:
        """Try upstream; on failure, fall back to local handler."""
        path = request.url.path
        upstream_path = path[len(prefix) :] or "/"
        upstream_url = f"{upstream_base}{upstream_path}"
        query = str(request.url.query)
        if query:
            upstream_url = f"{upstream_url}?{query}"

        # Circuit breaker: if upstream is known-down, skip directly to local
        if _circuit_breaker.is_open(upstream_base):
            logger.info(
                "CIRCUIT OPEN: skipping %s for %s %s -> falling back to local",
                upstream_base,
                request.method,
                path,
            )
            return await self._log_local(
                request,
                call_next,
                fallback="circuit_open",
                upstream_url=upstream_url,
            )

        # Try the upstream
        method = request.method
        fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        req_body = await request.body()

        try:
            async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
                upstream_resp = await client.request(
                    method=method,
                    url=upstream_url,
                    headers=fwd_headers,
                    content=req_body,
                    follow_redirects=True,
                )
        except httpx.RequestError as exc:
            # Upstream unreachable — open circuit and fall back
            _circuit_breaker.record_failure(upstream_base)
            logger.warning(
                "UPSTREAM FAILED: %s %s -> %s (%s) — falling back to local",
                method,
                path,
                upstream_url,
                type(exc).__name__,
            )
            _log_exchange(
                log_dir=self._settings.soundcork_log_dir,
                method=method,
                path=path,
                query=query,
                req_headers=fwd_headers,
                req_body=req_body,
                upstream_url=upstream_url,
                status=502,
                resp_headers={},
                resp_body=str(exc).encode(),
                fallback="upstream_error",
            )
            return await self._log_local(
                request,
                call_next,
                fallback="upstream_error",
                upstream_url=upstream_url,
            )

        resp_body = upstream_resp.content
        resp_headers = dict(upstream_resp.headers)

        # Log the upstream exchange (always, even if we fall back)
        _log_exchange(
            log_dir=self._settings.soundcork_log_dir,
            method=method,
            path=path,
            query=query,
            req_headers=fwd_headers,
            req_body=req_body,
            upstream_url=upstream_url,
            status=upstream_resp.status_code,
            resp_headers=resp_headers,
            resp_body=resp_body,
        )

        # If upstream returned 404 or 5xx, fall back to local handler
        # (e.g. Bose removed the API but the server still responds)
        if upstream_resp.status_code == 404 or upstream_resp.status_code >= 500:
            _circuit_breaker.record_failure(upstream_base)
            logger.warning(
                "UPSTREAM HTTP %d: %s %s -> %s — falling back to local",
                upstream_resp.status_code,
                method,
                path,
                upstream_url,
            )
            return await self._log_local(
                request,
                call_next,
                fallback=f"upstream_http_{upstream_resp.status_code}",
                upstream_url=upstream_url,
            )

        # Upstream responded successfully — record success (closes circuit)
        _circuit_breaker.record_success(upstream_base)

        # Strip content-encoding/content-length since httpx already decoded
        excluded = {"content-encoding", "content-length", "transfer-encoding"}
        return_headers = {k: v for k, v in resp_headers.items() if k.lower() not in excluded}

        return Response(
            content=resp_body,
            status_code=upstream_resp.status_code,
            headers=return_headers,
        )
