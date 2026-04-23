# Management API Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add management API endpoints (`/mgmt/*`) to SoundCork so the ueberboese-app can use it as its `apiUrl` for speaker management, device events, and Spotify integration.

**Architecture:** Add `/mgmt/*` routes to the existing FastAPI app with Basic Auth. Speaker/device data comes from the existing datastore. Spotify OAuth uses httpx (already a dependency) and stores tokens in `{data_dir}/spotify/accounts.json`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, httpx, file-based JSON storage.

---

## Phase 1: Auth + Speakers + Events

### Task 1: Add config settings

**Files:**
- Modify: `soundcork/config.py`

Add management auth and Spotify credential settings to the existing `Settings` class.

### Task 2: Basic Auth dependency

**Files:**
- Create: `soundcork/mgmt_auth.py`

FastAPI `Depends()` that validates HTTP Basic Auth against `mgmt_username`/`mgmt_password` from config.

### Task 3: Speaker list endpoint

**Files:**
- Create: `soundcork/mgmt.py`
- Modify: `soundcork/main.py` (include router)

`GET /mgmt/accounts/{accountId}/speakers` — reads device list from datastore, returns JSON with IP addresses and names.

### Task 4: Device events endpoint

**Files:**
- Modify: `soundcork/mgmt.py`

`GET /mgmt/devices/{deviceId}/events` — returns `{"events": []}` stub.

## Phase 2: Spotify Integration

### Task 5: Spotify service

**Files:**
- Create: `soundcork/spotify_service.py`

Handles OAuth flow (authorize URL, token exchange, token refresh) and Spotify Web API calls (user profile, entity resolution).

### Task 6: Spotify endpoints

**Files:**
- Modify: `soundcork/mgmt.py`

- `POST /mgmt/spotify/init` — returns authorize URL
- `GET /mgmt/spotify/callback` — server-side OAuth callback (for web/localhost testing)
- `POST /mgmt/spotify/confirm?code={code}` — exchanges code for tokens, stores account
- `GET /mgmt/spotify/accounts` — lists connected Spotify accounts
- `POST /mgmt/spotify/entity` — resolves Spotify URI to name + image

### Task 7: K8s deployment update

**Files:**
- Modify (in icteam-k8s repo): `clusters/kubernetes/soundcork/deployment.yaml`

Add `MGMT_USERNAME`, `MGMT_PASSWORD`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` env vars.
