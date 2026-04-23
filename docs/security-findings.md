# Security Findings

Security review performed 2026-02-20 against commit `40c1d8f` (application) and
`9536140` (icteam-k8s deployment). Deployment context: internet-exposed via
Traefik on a single-node Kubernetes cluster.

## Status Legend

- [ ] Open
- [x] Fixed

---

## Critical

### C-1: X-Forwarded-For Spoofing Bypasses IP Restriction

- **Status:** [x] Fixed (2026-02-21, commit `70c5fb6`)
- **Location:** `soundcork/main.py:187-192`

Changed `split(",")[0]` to `split(",")[-1]` so the middleware uses the
rightmost (Traefik-appended) XFF value instead of the attacker-controlled first
value. Added regression tests for XFF spoofing. Required C-5 as a prerequisite.

### C-2: All RFC1918 Private IPs Bypass Speaker Allowlist

- **Status:** [ ] Open (de-risked by C-1 + C-5 fixes)
- **Location:** `soundcork/speaker_allowlist.py:82-88`

```python
return ip in _LOOPBACK or ip in self._allowed_ips or _is_private_ip(ip)
```

Any RFC1918 address is auto-allowed. With C-1 fixed, internet attackers can no
longer spoof private IPs, so this is now a LAN-only exposure (any device on the
home network can access Bose protocol endpoints).

**Cannot remove `_is_private_ip()` as originally planned:** testing revealed the
speaker appears as `192.168.0.1` in XFF (NAT/routing between speaker subnet and
k8s node), not its registered IP `192.168.1.143`. Removing the private IP
fallback would break speaker traffic.

**Future fix:** Investigate the `192.168.0.1` routing path. Alternatively, add
a configurable `allowed_subnets` setting to restrict which private ranges are
accepted, instead of allowing all RFC1918.

### C-3: Default Management Credentials

- **Status:** [x] Fixed (2026-02-21, commit `02f9603`)
- **Location:** `soundcork/main.py` lifespan, `soundcork/config.py:27-28`

Server now raises `RuntimeError` during startup if `MGMT_PASSWORD` is still the
default `change_me!`. Prevents silent fallback to well-known credentials when
the K8s Secret is missing or misconfigured.

### C-4: Container Runs as Root

- **Status:** [x] Fixed (2026-02-20, commits `756ab9c` + `6377577`)
- **Location:** `Dockerfile`, `icteam-k8s deployment.yaml`

Added non-root user (UID 1000), `securityContext` with `runAsNonRoot`,
`readOnlyRootFilesystem`, `capabilities.drop: [ALL]`, and
`automountServiceAccountToken: false`.

### C-5: externalTrafficPolicy: Cluster Loses Real Client IPs

- **Status:** [x] Fixed (2026-02-21, icteam-k8s commit `dae1b6a`)
- **Location:** `icteam-k8s traefik Helm values`

Set `externalTrafficPolicy: Local` on the Traefik service. Verified real client
IPs now appear in XFF headers (public IPs for internet traffic, LAN IPs for
local traffic). Prerequisite for C-1.

---

## High

### H-1: XML Bomb Denial of Service

- **Status:** [ ] Open
- **Location:** `soundcork/datastore.py`, `soundcork/marge.py`, `soundcork/bmx.py`, `soundcork/devices.py`

`xml.etree.ElementTree` is used throughout without protection against entity
expansion bombs (billion laughs). A crafted XML body to any endpoint that
parses XML (presets, recents, device settings) can exhaust memory.

**Fix:** Replace with `defusedxml`:

```python
import defusedxml.ElementTree as ET
```

### H-2: Reflected XSS in Spotify Callback (3 instances)

- **Status:** [ ] Open
- **Location:** `soundcork/mgmt.py:147-174`

The `error` query parameter, Spotify `displayName`, and exception messages are
injected into HTML responses without escaping:

```python
f"<p>Error: {error}</p>"           # line 151 — attacker-controlled query param
f"<p>Linked account: {account['displayName']}</p>"  # line 166
f"<p>{e}</p>"                       # line 174 — exception detail
```

The callback endpoint (`GET /mgmt/spotify/callback`) requires no authentication.

**Fix:** Use `html.escape()` on all dynamic values, or return a generic error
message instead of reflecting input.

### H-3: SSRF via Image Proxy Redirect Following

- **Status:** [ ] Open
- **Location:** `soundcork/webui/routes.py:413`

The image proxy uses `follow_redirects=True`. The domain allowlist is checked
only on the initial URL. If an allowed CDN returns a redirect to an internal
address, the proxy follows it.

**Fix:** Set `follow_redirects=False`, or validate each redirect target against
the allowlist and private IP check.

### H-4: Unbounded In-Memory Session Store (DoS)

- **Status:** [ ] Open
- **Location:** `soundcork/webui/auth.py:14-36`

Sessions are never expired and there is no maximum count. Repeated login
requests create unlimited sessions until OOM.

**Fix:** Add a TTL (e.g., 24 hours) and a maximum session count. Evict oldest
sessions when the limit is reached.

### H-5: Unbounded OIDC Pending Flows (DoS)

- **Status:** [ ] Open
- **Location:** `soundcork/oidc.py:19,70`

The `_pending_flows` dict grows without bound. Each `GET /auth/login` creates a
new entry that is only removed on successful callback. No TTL, no maximum count.

**Fix:** Add TTL (e.g., 10 minutes) and maximum pending flow count.

### H-6: Unauthenticated Spotify OAuth Init

- **Status:** [ ] Open
- **Location:** `soundcork/mgmt.py:107-130`

`GET /mgmt/spotify/init` starts a Spotify OAuth flow without any authentication.
Any internet user can initiate flows, potentially linking arbitrary Spotify
accounts or exhausting Spotify API rate limits.

**Fix:** Require a valid WebUI session or Basic Auth.

### H-7: Spotify Tokens Stored in Plaintext

- **Status:** [ ] Open
- **Location:** `soundcork/spotify_service.py:49-53`

OAuth access and refresh tokens are stored as plaintext JSON at
`{data_dir}/spotify/accounts.json`. Refresh tokens do not expire.

**Fix:** Encrypt tokens at rest. At minimum, ensure file permissions are 0600.

### H-8: No Traefik Middleware on HTTPS Route

- **Status:** [ ] Open
- **Location:** `icteam-k8s soundcork/ingressroute.yaml`

The HTTPS IngressRoute has zero Traefik middleware — no rate limiting, no
security headers (HSTS, CSP, X-Frame-Options), no WAF. Compare to the Traefik
dashboard and RedisInsight which both use `require-authentik-login`.

**Fix:** Add at minimum:
- Rate-limiting middleware
- Security headers middleware (HSTS, CSP, X-Frame-Options, X-Content-Type-Options)
- Consider IP allowlisting or Authentik forwardAuth for `/mgmt/*` paths

---

## Medium

### M-1: Sensitive Headers Logged

- **Status:** [ ] Open
- **Location:** `soundcork/main.py:150-166`

When `LOG_REQUEST_HEADERS=true` (enabled in deployment), Authorization, Cookie,
and other sensitive headers are written to logs. Only the `host` header is
filtered.

**Fix:** Add a sensitive header filter:

```python
_SENSITIVE_HEADERS = {"authorization", "cookie", "x-csrf-token", "proxy-authorization"}
```

### M-2: Traffic Log Contains Auth Headers

- **Status:** [ ] Open
- **Location:** `soundcork/proxy.py:119-181`

In proxy mode, full request/response headers (including Authorization) are
logged to `traffic.jsonl` on the hostPath volume.

**Fix:** Strip sensitive headers before logging.

### M-3: No NetworkPolicy for SoundCork Namespace

- **Status:** [ ] Open
- **Location:** `icteam-k8s` (missing resource)

The soundcork pod can communicate with all other pods in all namespaces.

**Fix:** Add a NetworkPolicy restricting ingress to Traefik and egress to
required endpoints (DNS, Spotify API, Authentik, speakers on LAN).

### M-4: No Pod Security Standards on Namespace

- **Status:** [ ] Open
- **Location:** `icteam-k8s soundcork/namespace.yaml`

No PSS labels prevent deploying privileged containers in the namespace.

**Fix:** Add `pod-security.kubernetes.io/enforce: restricted` label.

### M-5: Unvalidated Path in Speaker Proxy

- **Status:** [ ] Open
- **Location:** `soundcork/webui/routes.py:344-363`

The `path` parameter is forwarded to the speaker without restriction. Any
endpoint on the speaker's port 8090 can be reached (including factory reset,
firmware update).

**Fix:** Allowlist safe speaker API paths.

### M-6: TuneIn Proxy Forwards Arbitrary Paths

- **Status:** [ ] Open
- **Location:** `soundcork/webui/routes.py:449-467`

User-controlled `path` and query parameters are forwarded to
`opml.radiotime.com`. If that service has open redirects, this becomes an SSRF
vector.

**Fix:** Limit allowed TuneIn API paths.

### M-7: Predictable Streaming Token

- **Status:** [ ] Open
- **Location:** `soundcork/main.py:617`

```python
token_value = f"st-local-token-{int(datetime.now().timestamp())}"
```

Timestamp-based token is trivially guessable.

**Fix:** Use `secrets.token_urlsafe()`.

### M-8: Race Conditions in Datastore File Operations

- **Status:** [ ] Open
- **Location:** `soundcork/datastore.py:329-338`, `soundcork/marge.py:280-281`

TOCTOU in `create_account()` / `add_device()` and acknowledged race condition
in recents.

**Fix:** Use `os.makedirs(exist_ok=True)` and file locking for concurrent
writes.

### M-9: OIDC CSRF Cookie Not HttpOnly

- **Status:** [ ] Open
- **Location:** `soundcork/oidc.py:142-148`

The CSRF token cookie is readable by JavaScript (`httponly=False`). Any XSS
vulnerability (H-2) immediately yields the CSRF token.

**Fix:** Acceptable pattern for SPAs, but fix H-2 first. Consider a
double-submit cookie pattern with HttpOnly.

---

## Low

### L-1: No Session Expiry

- **Status:** [ ] Open
- **Location:** `soundcork/webui/auth.py`

Sessions persist indefinitely until server restart or explicit logout.

**Fix:** Add `created_at` timestamp and expire after a configurable period.

### L-2: No Rate Limiting on Login Endpoints

- **Status:** [ ] Open
- **Location:** `soundcork/webui/routes.py:147-170`, `soundcork/mgmt_auth.py`

No rate limiting or account lockout on authentication endpoints.

**Fix:** Add rate limiting (e.g., `slowapi`) with exponential backoff.

### L-3: Secure Cookie Flag Conditional on Scheme

- **Status:** [ ] Open
- **Location:** `soundcork/webui/routes.py:168`

```python
secure=request.url.scheme == "https",
```

Behind a TLS-terminating proxy, `request.url.scheme` may be `http`. The session
cookie would then lack the `Secure` flag.

**Fix:** Trust `X-Forwarded-Proto` or always set `secure=True` in production.

### L-4: Relative File Paths for Static Data

- **Status:** [ ] Open
- **Location:** `soundcork/main.py:853,918`

`bmx_services.json` and `swupdate.xml` are opened with relative paths. Wrong
CWD causes crashes.

**Fix:** Use `os.path.dirname(__file__)` for absolute paths.

### L-5: Error Detail Leaks Internal State

- **Status:** [ ] Open
- **Location:** `soundcork/mgmt.py:198`, `soundcork/webui/routes.py:509-510`

Exception messages (which may contain file paths or API errors) are returned to
clients or sent as WebSocket close reasons.

**Fix:** Return generic error messages; log details server-side only.

### L-6: Image Tag Without Digest Pinning

- **Status:** [ ] Open
- **Location:** `icteam-k8s soundcork/deployment.yaml`

`ghcr.io/timvw/soundcork:main` with `imagePullPolicy: Always` — no immutable
tag or digest pinning.

**Fix:** Use semantic version tags or digest references for production.

---

## Remediation Priority

Completed:
- [x] **C-4** — container runs as non-root (2026-02-20)
- [x] **C-5** — externalTrafficPolicy: Local (2026-02-21)
- [x] **C-1** — XFF spoofing fix (2026-02-21)
- [x] **C-3** — startup credential validation (2026-02-21)

Next:
1. **H-2** (XSS) — trivially exploitable, no dependencies
2. **H-1** (defusedxml) — drop-in replacement
3. **H-3** (SSRF redirect) — small change
4. **H-4 + H-5** (bounded sessions/flows) — moderate effort
5. **H-6** (auth on spotify init) — small change
6. **H-8** (Traefik middleware) — k8s config only
7. **C-2** (allowlist refinement) — investigate 192.168.0.1 routing path
8. **M-1 through M-9** — medium effort, lower urgency
9. **L-1 through L-6** — low effort, low urgency
