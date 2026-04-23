# WebUI Session Auth Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Protect all `/webui/*` endpoints with session-based authentication using the existing `mgmt_username`/`mgmt_password` credentials, including CSRF protection for state-changing requests.

**Architecture:** Middleware on the webui router checks every request for a valid session cookie. Unauthenticated requests get redirected to a login page (HTML) or rejected with 401 (API) / 403 (WebSocket). Login verifies against `settings.mgmt_username`/`settings.mgmt_password` using `secrets.compare_digest()`. A CSRF token is generated per session and required on all mutating requests via `X-CSRF-Token` header.

**Tech Stack:** FastAPI middleware, `secrets.token_urlsafe()`, `secrets.compare_digest()`, vanilla JS `fetch()` wrapper.

---

### Task 1: Session store and auth helpers

**Files:**
- Create: `soundcork/webui/auth.py`
- Test: `tests/test_webui_auth.py`

### Task 2: Login page (standalone HTML)

**Files:**
- Create: `soundcork/webui/static/login.html`

### Task 3: Login/logout API endpoints

**Files:**
- Modify: `soundcork/webui/routes.py`
- Modify: `tests/test_webui_auth.py`

### Task 4: Auth middleware

**Files:**
- Modify: `soundcork/main.py`
- Modify: `soundcork/webui/auth.py`
- Modify: `tests/test_webui_auth.py`

### Task 5: CSRF protection

**Files:**
- Modify: `soundcork/main.py`
- Modify: `tests/test_webui_auth.py`

### Task 6: Frontend 401 handler and CSRF header injection

**Files:**
- Modify: `soundcork/webui/static/app.js`

### Task 7: Fix existing tests for auth

**Files:**
- Modify: `tests/test_ip_restriction.py`

### Task 8: WebSocket auth verification

**Files:**
- Modify: `tests/test_webui_auth.py`
