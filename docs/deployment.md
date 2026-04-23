# Deployment Guide

Four ways to run SoundCork, from simplest to most customizable.

## Option 1: Docker (Simplest)

```bash
docker run -d --name soundcork \
  -p 8000:8000 \
  -v /path/to/your/data:/soundcork/data \
  -e base_url=http://your-server:8000 \
  -e data_dir=/soundcork/data \
  ghcr.io/timvw/soundcork:main
```

## Option 2: Docker Compose

Create a `docker-compose.yml`:

```yaml
services:
  soundcork:
    image: ghcr.io/timvw/soundcork:main
    ports:
      - "8000:8000"
    environment:
      - base_url=http://your-server:8000
      - data_dir=/soundcork/data
      - SOUNDCORK_MODE=local
      - SOUNDCORK_LOG_DIR=/soundcork/logs/traffic
      # Optional: OIDC/SSO authentication (see Authentication section below)
      # - OIDC_ISSUER_URL=https://your-provider/application/o/soundcork/
      # - OIDC_CLIENT_ID=soundcork
      # - OIDC_CLIENT_SECRET=your-secret
    volumes:
      - ./data:/soundcork/data
      - ./logs:/soundcork/logs
    restart: unless-stopped
```

Then run:

```bash
docker compose up -d
```

## Option 3: Kubernetes

This is our production setup. Customize the hostname, volume paths, and ingress controller for your environment.

### Namespace

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: soundcork
```

### Deployment

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: soundcork
  namespace: soundcork
spec:
  replicas: 1
  selector:
    matchLabels:
      app: soundcork
  template:
    metadata:
      labels:
        app: soundcork
    spec:
      containers:
        - name: soundcork
          image: ghcr.io/timvw/soundcork:main
          ports:
            - containerPort: 8000
          env:
            - name: base_url
              value: "https://soundcork.example.com"
            - name: data_dir
              value: "/soundcork/data"
            - name: SOUNDCORK_MODE
              value: "local"
            - name: SOUNDCORK_LOG_DIR
              value: "/soundcork/logs/traffic"
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
          volumeMounts:
            - name: data
              mountPath: /soundcork/data
            - name: logs
              mountPath: /soundcork/logs
      volumes:
        - name: data
          hostPath:
            path: /srv/soundcork/data
            type: DirectoryOrCreate
        - name: logs
          hostPath:
            path: /srv/soundcork/logs
            type: DirectoryOrCreate
```

> **Note:** This example uses `hostPath` volumes. Adapt the volume type for your cluster (e.g., `persistentVolumeClaim`, NFS, or a CSI driver).

### Service

```yaml
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: soundcork
  namespace: soundcork
spec:
  type: ClusterIP
  selector:
    app: soundcork
  ports:
    - port: 8000
      targetPort: 8000
```

### Ingress

```yaml
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: soundcork
  namespace: soundcork
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
spec:
  tls:
    - hosts:
        - soundcork.example.com
      secretName: soundcork-tls
  rules:
    - host: soundcork.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: soundcork
                port:
                  number: 8000
```

> **Note:** We use Traefik IngressRoute in our setup. Adapt the ingress for your controller (nginx, Traefik, etc.).

### Apply

```bash
kubectl apply -f namespace.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml
```

## Option 4: Bare Metal

### Prerequisites

- Python 3.12

### Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Running

**Development:**

```bash
fastapi dev soundcork/main.py
```

**Production:**

```bash
gunicorn -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 soundcork.main:app
```

### Systemd

A sample unit file is included at `soundcork.service.example`. Copy it to `/etc/systemd/system/soundcork.service`, adjust paths and user, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now soundcork
```

> **Note:** Make sure `PYTHONPATH` includes the project root and that the working directory is set correctly in your service file or shell environment.

## Environment Variables

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `base_url` | `""` | Public URL of your SoundCork instance (e.g., `https://soundcork.example.com`) |
| `data_dir` | `""` | Path to the speaker data directory |
| `SOUNDCORK_MODE` | `local` | `local` (recommended) or `proxy` — see [Architecture](architecture.md) |
| `SOUNDCORK_LOG_DIR` | `./logs/traffic` | Directory for traffic logs (proxy mode only) |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `MGMT_USERNAME` | `admin` | Username for password-based WebUI and management API login |
| `MGMT_PASSWORD` | `change_me!` | Password for password-based WebUI and management API login |
| `OIDC_ISSUER_URL` | `""` | OIDC provider issuer URL (e.g., `https://authentik.example.com/application/o/soundcork/`) |
| `OIDC_CLIENT_ID` | `""` | OIDC client ID |
| `OIDC_CLIENT_SECRET` | `""` | OIDC client secret |

When all three `OIDC_*` variables are set, the WebUI login page shows a "Sign in with SSO" button and authenticates users via your OIDC provider. When any is empty, the WebUI falls back to password-based login using `MGMT_USERNAME`/`MGMT_PASSWORD`.

### Spotify (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `SPOTIFY_CLIENT_ID` | `""` | Spotify OAuth client ID — see [Spotify Guide](spotify.md) |
| `SPOTIFY_CLIENT_SECRET` | `""` | Spotify OAuth client secret |

## Authentication

SoundCork has three layers of authentication:

| Layer | Protects | Mechanism |
|-------|----------|-----------|
| Speaker IP allowlist | `/marge/*`, `/bmx/*`, `/oauth/*` (Bose protocol endpoints) | Only registered speaker IPs can reach these endpoints |
| WebUI session auth | `/webui/*` | Cookie-based sessions — login via password or OIDC |
| Management API auth | `/mgmt/*` | HTTP Basic Auth (`MGMT_USERNAME`/`MGMT_PASSWORD`) |

### OIDC / SSO Setup

SoundCork supports authentication via any standard OpenID Connect provider. It uses the authorization code flow with PKCE and auto-discovers endpoints from the provider's `.well-known/openid-configuration`.

**Tested providers:** Authentik, Keycloak. Any OIDC-compliant provider should work.

**Steps:**

1. Create an OAuth2/OIDC application in your provider with:
   - **Client type:** Confidential
   - **Grant type:** Authorization Code
   - **Redirect URI:** `https://your-soundcork-url/auth/callback`
   - **Scopes:** `openid`, `email`, `profile`

2. Set the three environment variables:
   ```bash
   OIDC_ISSUER_URL=https://your-provider/application/o/soundcork/
   OIDC_CLIENT_ID=soundcork
   OIDC_CLIENT_SECRET=your-client-secret
   ```

3. Restart SoundCork. The login page will now show a "Sign in with SSO" button.

**Notes:**
- Password login remains available as a fallback even when OIDC is enabled (the password form is hidden from the UI but the API endpoint still works).
- Sessions are in-memory — on server restart, users simply re-authenticate (seamless if already logged in to the SSO provider).
- Logout clears the SoundCork session only; it does not log the user out of the SSO provider.
- For local development, add `http://localhost:8000/auth/callback` as an additional redirect URI in your provider.

## Container Image

- **Image:** `ghcr.io/timvw/soundcork:main`
- **Multi-architecture:** `linux/amd64` + `linux/arm64` (works on Raspberry Pi)
- Built automatically via GitHub Actions on every push to main
- Source: see `.github/workflows/docker-publish.yml`

## Verifying It Works

```bash
curl http://your-server:8000/
# Expected: {"Bose":"Can't Brick Us"}
```

After redirecting your speaker (see [Speaker Setup](speaker-setup.md)), you should see incoming requests in the server logs.
