# SpendWise API

A production-ready expense tracking REST API built with **FastAPI**, **PostgreSQL** (SQLAlchemy Async + Alembic), **Keycloak** (OAuth 2.0 / OIDC JWT verification), and **Frankfurter** (async currency exchange conversion).

---

## Live Deployment

- **API Base URL:** `<YOUR_RENDER_API_URL>` *(update after Render deploy, e.g. `https://spendwise-api.onrender.com`)*
- **Interactive Docs (Swagger):** `<YOUR_RENDER_API_URL>/docs`
- **Health Check:** `<YOUR_RENDER_API_URL>/health`

---

## Architecture Overview

- **Keycloak** handles authentication, user registration, password verification, and role assignment (`USER`, `ADMIN`).
- **FastAPI** acts as an OAuth 2.0 Resource Server: it fetches Keycloak's JWKS public keys, verifies `RS256` JWT signatures, checks `iss` / `aud` / `exp` claims, and enforces ownership (`owner_id == token.sub`) on every query.
- **PostgreSQL** stores `categories` and `expenses` with exact `NUMERIC(12, 2)` (`Decimal`) monetary amounts, foreign-key restrictions, and Alembic migrations.
- **Frankfurter Client** (`httpx.AsyncClient`) performs live currency conversion with explicit connect/read timeouts and maps upstream failures to `400`, `502`, or `503`.

---

## Local Development Setup

### 1. Prerequisites
- Docker & Docker Compose
- Python 3.11+ (optional for local lint/type checks)

### 2. Configure Environment
```bash
cp .env.example .env
```

### 3. Start Services (API, PostgreSQL, Keycloak)
```bash
docker compose up -d --build
```
Keycloak automatically imports the `spendwise` realm from `keycloak/realm-export.json` (`testuser` / `testuser123`, `adminuser` / `adminuser123`).

### 4. Apply Database Migrations
```bash
docker exec spendwise-api alembic upgrade head
```

### 5. Verify Local Service
- Swagger UI: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`
- Readiness (DB probe): `http://localhost:8000/ready`

---

## Running Tests & Quality Checks

Run the full test suite (hermetic + DB integration tests) inside the container:
```bash
docker exec spendwise-api pytest -vv
```

Run formatting, linting, and static type checking locally:
```bash
ruff format --check .
ruff check .
mypy app tests
```

---

## Example API Calls (`curl`)

### 1. Obtain a JWT Access Token from Keycloak
```bash
TOKEN=$(curl -s -X POST "http://localhost:8080/realms/spendwise/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=spendwise-api" \
  -d "username=testuser" \
  -d "password=testuser123" \
  -d "grant_type=password" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
```

### 2. Create a Category & Expense
```bash
curl -X POST "http://localhost:8000/api/v1/categories" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Groceries"}'

curl -X POST "http://localhost:8000/api/v1/expenses" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Weekly groceries", "amount": "45.50", "currency": "USD", "category_id": "<CATEGORY_UUID>"}'
```

### 3. Convert Currency
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/exchange-rates/convert?amount=100&from=USD&to=INR"
```

---

## Deploying to Render

This repository includes [`render.yaml`](render.yaml), [`Dockerfile`](Dockerfile), and [`Dockerfile.keycloak`](Dockerfile.keycloak) for Blueprint deployment on Render:

1. Push your code to GitHub (`main` branch).
2. In the **Render Dashboard**, click **New +** ➔ **Blueprint** and select this repository.
3. Render creates:
   - `spendwise-db` (PostgreSQL)
   - `spendwise-keycloak` (Keycloak Docker service)
   - `spendwise-api` (FastAPI Docker service, automatically running `alembic upgrade head` on deploy)
4. Set the secret/environment variables prompted by Render:
   - On `spendwise-keycloak`: `KC_BOOTSTRAP_ADMIN_USERNAME`, `KC_BOOTSTRAP_ADMIN_PASSWORD`
   - On `spendwise-api` (after `spendwise-keycloak` gets its `onrender.com` URL):
     - `KEYCLOAK_ISSUER=https://<your-keycloak-service>.onrender.com/realms/spendwise`
     - `KEYCLOAK_JWKS_URL=https://<your-keycloak-service>.onrender.com/realms/spendwise/protocol/openid-connect/certs`
5. Verify `/health`, `/ready`, `/docs`, and token-authenticated requests against your live Render URL.
