# SpendWise API — FastAPI + PostgreSQL + Keycloak

## 1. Project overview

Build **SpendWise**, a production-style expense-tracking REST API. Users can manage their own expenses and categories, while administrators can inspect system-level information. The service uses **Keycloak as the authorization server** and **FastAPI as the resource server**.

The deployed application must work without any LLM or AI service. A coding agent may help during development, but the finished API must be understandable, testable, and maintainable without one.

### Core stack

| Area | Technology |
|---|---|
| Language | Python 3.11+ |
| API | FastAPI |
| Validation | Pydantic v2 |
| Database | PostgreSQL |
| ORM / database access | SQLAlchemy 2.x async |
| Migrations | Alembic |
| Authentication / authorization | Keycloak (OIDC, OAuth 2.0, JWT) |
| HTTP client | HTTPX (async) |
| External API | Frankfurter exchange-rate API |
| Testing | Pytest, HTTPX |
| Code quality | Ruff, mypy (or Pyright) |
| Containers | Docker, Docker Compose |
| Version control | Git |
| Deployment | Any Docker-capable host with public networking |

---

## 2. What the application does

A registered user can:

- Create, list, view, update, and delete their own expenses.
- Create and manage their own expense categories.
- Filter expenses by category, currency, and date range.
- Request a currency conversion estimate using the external exchange-rate service.
- View a summary of their own spending.

An administrator can:

- List users' expense records for support or moderation.
- View basic service statistics.
- Access admin-only endpoints.

**Important ownership rule:** a normal user must never be able to read, update, or delete another user's expenses or categories by changing an ID in the URL.

### Suggested roles

Create these realm roles in Keycloak:

- `USER` — normal authenticated application user.
- `ADMIN` — administrator with access to admin endpoints.

For the first version, assign `USER` to normal users and assign `ADMIN` only to an administrator account. Do not implement your own password storage or login endpoint in FastAPI. Keycloak handles login and token issuance.

---

## 3. Architecture

```text
                 User / API client
                         |
                         | Bearer access token
                         v
                +------------------+
                |    FastAPI API   |
                |                  |
                | JWT verification |
                | Role checks      |
                | Request schemas  |
                +--------+---------+
                         |
             +-----------+------------+
             |                        |
             v                        v
      +-------------+        +------------------+
      | PostgreSQL  |        | Frankfurter API  |
      | expenses    |        | exchange rates   |
      | categories  |        +------------------+
      +-------------+
             ^
             |
      +------+------+
      |   Alembic   |
      | migrations  |
      +-------------+

      +------------------+
      |     Keycloak     |
      | Identity provider|
      | OIDC / OAuth 2.0 |
      | JWT + realm roles|
      +------------------+
```

### Responsibility boundaries

- **Keycloak:** user login, identity, token issuance, and role assignment.
- **FastAPI:** verifies access tokens, enforces authorization, validates input, runs business logic, and returns HTTP responses.
- **PostgreSQL:** stores application data.
- **Frankfurter:** supplies exchange-rate data. It is not an authentication provider.
- **Docker Compose:** provides a reproducible local development environment.

FastAPI is an OAuth 2.0 resource server in this design. It does not receive or store users' passwords.

---

## 4. Authentication and authorization design

### Keycloak setup

Run Keycloak locally with Docker Compose. Create:

1. A realm named `spendwise`.
2. A confidential or public client appropriate for your chosen client flow. For local Swagger testing, a public client with Authorization Code + PKCE is a reasonable option if configured correctly.
3. Realm roles `USER` and `ADMIN`.
4. A normal test user with the `USER` role.
5. An administrator test user with the `ADMIN` role.
6. A client scope or protocol-mapper configuration that places realm roles in the access token under `realm_access.roles`.

Use the realm's OpenID Connect discovery document and JWKS endpoint. Do not hardcode signing keys.

Typical local endpoints (adjust to your Compose configuration):

```text
Issuer:
http://localhost:8080/realms/spendwise

OIDC discovery:
http://localhost:8080/realms/spendwise/.well-known/openid-configuration

JWKS:
http://localhost:8080/realms/spendwise/protocol/openid-connect/certs
```

### Token verification in FastAPI

For each protected request:

1. Read the `Authorization: Bearer <token>` header.
2. Verify the JWT signature using Keycloak's public keys (JWKS).
3. Validate the expected issuer.
4. Validate the expected audience/client claim according to your Keycloak token configuration.
5. Validate expiry (`exp`) and other standard time claims.
6. Extract the stable user identifier from `sub`.
7. Extract roles from the configured token claim.
8. Reject invalid or missing tokens with `401 Unauthorized`.
9. Reject authenticated users without the required role with `403 Forbidden`.

Use a maintained JWT/JWKS library and cache signing keys. Handle key rotation by refreshing the JWKS when an unknown `kid` is encountered. Never simply decode a JWT without verifying its signature.

### Authorization rules

| Operation | USER | ADMIN |
|---|---:|---:|
| Manage own expenses | Yes | Yes |
| Read another user's expenses | No | Yes |
| Manage own categories | Yes | Yes |
| Read service statistics | No | Yes |
| Access admin endpoints | No | Yes |

Authorization must be enforced on the server, not merely hidden in frontend controls.

---

## 5. Data model

Use UUID primary keys and UTC timestamps.

### `categories`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `owner_id` | String | Keycloak `sub` of the owner |
| `name` | String | Required; unique per owner |
| `created_at` | Timestamp | UTC |

### `expenses`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `owner_id` | String | Keycloak `sub` of the owner |
| `category_id` | UUID | Foreign key to categories |
| `title` | String | Required |
| `amount` | Numeric(12, 2) | Must be greater than zero |
| `currency` | String(3) | ISO currency code, e.g. INR, USD |
| `spent_at` | Timestamp | Date/time the expense occurred |
| `notes` | Text | Optional |
| `created_at` | Timestamp | UTC |
| `updated_at` | Timestamp | UTC |

Add indexes for `owner_id`, `spent_at`, and commonly filtered fields. Ensure a category belongs to the same owner before associating it with an expense. Consider database constraints as well as application validation.

### Data integrity rules

- Amount must be greater than zero.
- Currency must be a valid three-letter code (validate against a supported list or a reliable currency-code library).
- Category names must not be blank.
- A user can only attach their own category to an expense.
- Deleting a category that is still in use should either be rejected with `409 Conflict` or handled by a clearly documented policy.
- Use `Decimal`, not binary floating-point, for money.

---

## 6. REST API design

Use the prefix `/api/v1`.

### Health

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/health` | Liveness check | No |
| GET | `/ready` | Database readiness check | No |

Do not expose secrets, connection strings, or internal exception details in health responses.

### Categories

| Method | Path | Purpose |
|---|---|---|
| POST | `/categories` | Create a category |
| GET | `/categories` | List current user's categories |
| GET | `/categories/{category_id}` | Get one owned category |
| PATCH | `/categories/{category_id}` | Update an owned category |
| DELETE | `/categories/{category_id}` | Delete an owned category |

All category routes require authentication. Scope database queries by the authenticated user's `sub`.

### Expenses

| Method | Path | Purpose |
|---|---|---|
| POST | `/expenses` | Create an expense |
| GET | `/expenses` | List expenses with pagination and filters |
| GET | `/expenses/{expense_id}` | Get one owned expense |
| PATCH | `/expenses/{expense_id}` | Partially update an owned expense |
| DELETE | `/expenses/{expense_id}` | Delete an owned expense |
| GET | `/expenses/summary` | Get the user's spending summary |

Suggested list filters:

```text
GET /api/v1/expenses?page=1&page_size=20
GET /api/v1/expenses?category_id=<uuid>
GET /api/v1/expenses?from_date=2026-01-01&to_date=2026-01-31
GET /api/v1/expenses?currency=INR
```

Set a maximum page size (for example, 100). Validate that page numbers and page sizes are positive.

### Currency conversion (external API)

| Method | Path | Purpose |
|---|---|---|
| GET | `/exchange-rates/convert` | Convert an amount between currencies |

Example:

```text
GET /api/v1/exchange-rates/convert?amount=100&from=USD&to=INR
```

Use the Frankfurter API from the backend with `httpx.AsyncClient`. Keep the external API URL in configuration. Apply a timeout, validate inputs, and return a predictable response.

Example response shape:

```json
{
  "amount": "100.00",
  "from_currency": "USD",
  "to_currency": "INR",
  "rate": "83.12",
  "converted_amount": "8312.00",
  "rate_date": "2026-01-15"
}
```

The values above are illustrative only; always use the live API response. Document that exchange rates are informational and may not match a bank's transaction rate. Do not persist a converted value as the original expense amount.

### Admin

| Method | Path | Purpose | Required role |
|---|---|---|---|
| GET | `/admin/expenses` | List expenses across users (with pagination) | `ADMIN` |
| GET | `/admin/stats` | Basic aggregate service statistics | `ADMIN` |

Avoid returning unnecessary personal data from admin endpoints.

---

## 7. Request and response schemas

Use separate Pydantic schemas for input and output. Do not expose SQLAlchemy model objects directly.

Suggested schemas:

```text
CategoryCreate
CategoryUpdate
CategoryRead

ExpenseCreate
ExpenseUpdate
ExpenseRead
ExpenseListResponse
ExpenseSummary

CurrencyConversionResponse
ErrorResponse
```

Example `ExpenseCreate` payload:

```json
{
  "title": "Groceries",
  "amount": "1250.50",
  "currency": "INR",
  "category_id": "00000000-0000-0000-0000-000000000000",
  "spent_at": "2026-01-15T18:30:00Z",
  "notes": "Weekly groceries"
}
```

The API must derive `owner_id` from the verified token. Never accept `owner_id` from a normal user's request body.

Use consistent response formats and appropriate status codes:

- `200 OK` — successful read or update.
- `201 Created` — successful creation.
- `204 No Content` — successful deletion.
- `400 Bad Request` — malformed or semantically invalid request where appropriate.
- `401 Unauthorized` — missing or invalid authentication.
- `403 Forbidden` — authenticated but insufficient role.
- `404 Not Found` — resource does not exist or is not visible to this user.
- `409 Conflict` — uniqueness or state conflict.
- `422 Unprocessable Entity` — request schema validation failure.
- `502 Bad Gateway` — invalid or failed upstream response.
- `503 Service Unavailable` — upstream service unavailable, if that is the documented policy.
- `500 Internal Server Error` — unexpected server failure.

For user-owned resources, returning `404` for another user's resource avoids confirming that the resource exists.

---

## 8. External API integration and failure handling

Use the Frankfurter API for currency rates. The integration should:

- Use asynchronous HTTP requests with HTTPX.
- Have explicit connection and read timeouts.
- Validate the upstream response before using it.
- Handle unsupported currency pairs and missing rates.
- Handle timeouts, connection failures, non-success HTTP statuses, and malformed JSON.
- Avoid exposing upstream stack traces or raw internal details to clients.
- Log enough context to debug failures without logging access tokens or secrets.

Suggested mapping:

| Failure | API behavior |
|---|---|
| Invalid amount or currency input | `422` |
| Unsupported currency pair | `400` or documented `422` |
| Upstream timeout | `503` |
| Upstream connection / server failure | `502` or `503` |
| Malformed upstream response | `502` |
| Unexpected application error | Generic `500` response |

Do not retry every error blindly. If retries are added, limit the number and only retry transient failures.

---

## 9. Suggested repository structure

```text
spendwise-api/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── security.py
│   ├── api/
│   │   ├── dependencies.py
│   │   └── v1/
│   │       ├── router.py
│   │       └── endpoints/
│   │           ├── health.py
│   │           ├── categories.py
│   │           ├── expenses.py
│   │           ├── exchange_rates.py
│   │           └── admin.py
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py
│   │   └── models/
│   │       ├── category.py
│   │       └── expense.py
│   ├── schemas/
│   │   ├── category.py
│   │   ├── expense.py
│   │   └── exchange_rate.py
│   ├── repositories/
│   │   ├── categories.py
│   │   └── expenses.py
│   ├── services/
│   │   ├── categories.py
│   │   ├── expenses.py
│   │   └── exchange_rates.py
│   └── integrations/
│       └── frankfurter.py
├── migrations/
│   └── versions/
├── tests/
│   ├── conftest.py
│   ├── test_health.py
│   ├── test_auth.py
│   ├── test_categories.py
│   ├── test_expenses.py
│   ├── test_exchange_rates.py
│   └── test_admin.py
├── keycloak/
│   └── realm-export.json
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

Keep the architecture simple. Do not create an abstraction or layer unless it solves a real problem. A repository/service split is optional; if used, keep responsibilities clear and avoid duplicating business logic.

---

## 10. Configuration and secrets

Use Pydantic Settings (or an equivalent typed configuration layer). Read configuration from environment variables.

Example `.env.example`:

```dotenv
APP_NAME=SpendWise API
APP_ENV=local
LOG_LEVEL=INFO

DATABASE_URL=postgresql+asyncpg://spendwise:spendwise@db:5432/spendwise

KEYCLOAK_ISSUER=http://keycloak:8080/realms/spendwise
KEYCLOAK_JWKS_URL=http://keycloak:8080/realms/spendwise/protocol/openid-connect/certs
KEYCLOAK_AUDIENCE=spendwise-api

FRANKFURTER_BASE_URL=https://api.frankfurter.dev
EXTERNAL_API_TIMEOUT_SECONDS=5
```

The exact Keycloak audience value depends on the client/audience mapper configuration. Configure it deliberately and verify a real token contains the expected claim.

Rules:

- Commit `.env.example`, never commit `.env`.
- Never put client secrets, database passwords, or signing keys in Git.
- Use separate local and production settings.
- In production, use the deployment platform's secret/environment-variable manager.
- Do not disable TLS certificate verification in production.

---

## 11. Docker and local development

Use Docker Compose to run at least:

- `api` — FastAPI application.
- `db` — PostgreSQL.
- `keycloak` — Keycloak server.

For local development, Keycloak may use its development start command. Do not use development mode or embedded development credentials for a public production deployment.

The API container should:

- Run as a non-root user where practical.
- Install pinned or lockfile-controlled dependencies.
- Expose the application port.
- Use a health check where appropriate.
- Start with a production ASGI server configuration (for example, Uvicorn).
- Avoid baking `.env` secrets into the image.

Use named Docker volumes for PostgreSQL and Keycloak data if persistence is required locally.

Example commands (adapt to your final project files):

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f api
docker compose down
```

Do not use `docker compose down -v` unless you intentionally want to delete local database volumes.

---

## 12. Database migrations

Use Alembic for schema changes.

Expected workflow:

```bash
alembic revision --autogenerate -m "create expenses and categories"
alembic upgrade head
alembic current
```

Review every autogenerated migration before applying it. Do not rely on `create_all()` as the production migration strategy.

---

## 13. Testing strategy

Use Pytest and HTTPX. Tests should run without depending on a live production Keycloak or the public exchange-rate service.

### Minimum automated test coverage

**Health**
- Liveness returns success.
- Readiness reports database unavailable cleanly.

**Authentication**
- Missing token returns `401`.
- Malformed token returns `401`.
- Expired token returns `401`.
- Wrong issuer or audience returns `401`.
- Valid `USER` token can access user routes.
- `USER` token cannot access admin routes (`403`).
- `ADMIN` token can access admin routes.

**Categories**
- Create and list categories.
- Reject blank category names.
- User cannot access another user's category.
- Duplicate category behavior is tested.
- Deleting a category in use follows the documented conflict policy.

**Expenses**
- Create, list, retrieve, update, and delete an expense.
- Reject zero or negative amounts.
- Reject invalid currency codes.
- Reject a category owned by another user.
- User A cannot read, update, or delete User B's expense.
- Pagination and date filters work.

**External API**
- Successful conversion.
- Upstream timeout.
- Upstream non-success response.
- Invalid or malformed upstream payload.
- Unsupported currency pair.

Mock the external API at the HTTP boundary. Do not make automated tests flaky by relying on internet availability.

### Quality checks

Add scripts or documented commands for:

```bash
pytest
ruff check .
ruff format --check .
mypy app
```

If mypy is too strict for the initial stage, configure it deliberately and improve coverage incrementally rather than silently skipping checks.

---

## 14. Logging and error responses

Use Python's standard logging with a consistent format. Include useful fields such as:

- Timestamp and log level.
- Request ID (generate one if the client does not provide one).
- HTTP method and path.
- Response status and duration.
- Relevant non-sensitive error context.

Never log:

- Bearer access tokens.
- Passwords.
- Client secrets.
- Database credentials.
- Full sensitive request bodies.

Return a consistent error shape, for example:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Expense not found"
  }
}
```

In production, unexpected errors should return a generic message. Keep detailed stack traces in protected server logs only.

---

## 15. Git workflow and coding-agent review

Use Git from the beginning.

Suggested branch workflow:

```text
main
  └── feature/database-models
  └── feature/keycloak-auth
  └── feature/expense-crud
  └── feature/exchange-rate-integration
  └── feature/tests-and-deployment
```

For each meaningful coding-agent change:

1. Ask for a small, scoped change.
2. Inspect `git status` and `git diff`.
3. Read the changed files, not just the summary.
4. Check for security issues, unnecessary complexity, missing tests, and incorrect assumptions.
5. Run tests, linting, type checking, and relevant manual API calls.
6. Only then commit the change.

Useful commands:

```bash
git status
git diff
git diff --staged
git diff --check
git log --oneline
```

Do not accept a generated change merely because it compiles.

---

## 16. Deployment checklist

Deploy the API, PostgreSQL, and Keycloak in a way that is appropriate for the chosen host. If the platform cannot run all services reliably, use managed PostgreSQL and a separately hosted Keycloak instance.

Before deployment:

- Configure a public HTTPS URL for the API.
- Configure a persistent PostgreSQL database.
- Configure Keycloak with a stable public HTTPS issuer URL.
- Ensure the issuer in the access token exactly matches the issuer expected by FastAPI.
- Configure the correct audience mapper and verify a real access token.
- Configure production secrets as environment variables.
- Apply Alembic migrations.
- Configure CORS only for the actual client origins if a browser frontend is added.
- Disable Keycloak development mode.
- Configure backups and basic monitoring/log access.

**Important Keycloak networking note:** the `iss` claim in a JWT must match the issuer configured in FastAPI exactly. A container-internal URL such as `http://keycloak:8080/...` and a public URL such as `https://auth.example.com/...` are not interchangeable. Design the issuer and network configuration before deployment, and test token verification from the deployed API.

---

## 17. Deployed API verification

After deployment, verify the real public service.

### OpenAPI

Open:

```text
https://YOUR_API_HOST/docs
https://YOUR_API_HOST/openapi.json
```

Use the Swagger Authorize flow if it has been configured for your Keycloak client. Otherwise obtain a token through the documented Keycloak flow and paste it as a Bearer token.

### cURL examples

Health:

```bash
curl -i https://YOUR_API_HOST/health
```

Protected route without a token (should return `401`):

```bash
curl -i https://YOUR_API_HOST/api/v1/expenses
```

Create an expense with a valid token:

```bash
curl -i -X POST "https://YOUR_API_HOST/api/v1/expenses" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Lunch",
    "amount": "180.00",
    "currency": "INR",
    "category_id": "YOUR_CATEGORY_UUID",
    "spent_at": "2026-01-15T13:00:00Z"
  }'
```

List expenses:

```bash
curl -i "https://YOUR_API_HOST/api/v1/expenses?page=1&page_size=20" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

Currency conversion:

```bash
curl -i "https://YOUR_API_HOST/api/v1/exchange-rates/convert?amount=100&from=USD&to=INR"
```

Do not publish real access tokens in the README, screenshots, issues, or Git history.

---

## 18. Required AI-coding failure report

Create `docs/ai-coding-review.md` and document one real failure from the coding-agent-assisted build.

Use this template. Do not invent a failure; record an actual one you encounter.

```markdown
# AI Coding Review — One Failure

## Context
What feature were you implementing?

## What the coding agent proposed
Describe the generated code or design.

## Why it was wrong or suboptimal
Explain the bug, security weakness, missing behavior, or unnecessary complexity.

## How I detected it
Mention the diff review, test, type checker, log, or manual API call that exposed it.

## What I changed
Describe the final implementation.

## Engineering lesson
What will I check more carefully next time?
```

Possible areas to watch for (examples only; document only what actually happens):

- Decoding a JWT without verifying its signature.
- Trusting a user ID supplied in the request body instead of the token's `sub`.
- Forgetting to scope a database query by the authenticated user.
- Accepting a category belonging to another user.
- Using floating-point arithmetic for currency.
- Not setting a timeout on the external HTTP request.
- Returning raw exception details to API clients.
- Creating migrations that drop or alter data unexpectedly.

---

## 19. Build milestones

Work in small milestones. Do not start with every feature at once.

### Milestone 1 — Project foundation
- [ ] Create repository and Python environment.
- [ ] Add FastAPI app and `/health`.
- [ ] Add configuration and `.env.example`.
- [ ] Add Ruff and Pytest.
- [ ] Add Dockerfile and Compose with PostgreSQL and Keycloak.

**Exit condition:** the API, database, and Keycloak start locally and the health endpoint responds.

### Milestone 2 — Database
- [ ] Add SQLAlchemy async engine and session dependency.
- [ ] Add expense and category models.
- [ ] Add Alembic.
- [ ] Create and inspect the first migration.
- [ ] Add database tests.

**Exit condition:** migrations work from a clean database and models persist correctly.

### Milestone 3 — Keycloak security
- [ ] Create the realm, client, and roles.
- [ ] Obtain a real access token.
- [ ] Implement JWT signature and claim validation using JWKS.
- [ ] Implement current-user and role dependencies.
- [ ] Test `401`, `403`, invalid issuer, invalid audience, and expired-token cases.

**Exit condition:** protected endpoints accept valid tokens and reject invalid ones.

### Milestone 4 — CRUD and ownership
- [ ] Implement category CRUD.
- [ ] Implement expense CRUD.
- [ ] Add pagination and filters.
- [ ] Enforce ownership in every user-level database query.
- [ ] Add summary and admin endpoints.
- [ ] Add tests for cross-user access.

**Exit condition:** all CRUD operations work and users cannot access each other's records.

### Milestone 5 — External API
- [ ] Implement Frankfurter client with HTTPX async.
- [ ] Add timeout and upstream response validation.
- [ ] Map external-service failures to stable API errors.
- [ ] Mock upstream behavior in tests.

**Exit condition:** conversion works and all expected upstream failure paths are tested.

### Milestone 6 — Hardening
- [ ] Add request IDs and structured/useful logging.
- [ ] Add consistent error responses.
- [ ] Run tests, Ruff, and type checking.
- [ ] Review security-sensitive code and all Git diffs.
- [ ] Write the AI coding failure report.

**Exit condition:** quality checks pass and the failure report describes a real observed issue.

### Milestone 7 — Ship
- [ ] Finalize Docker production configuration.
- [ ] Deploy API, database, and Keycloak.
- [ ] Configure HTTPS, secrets, issuer, and audience.
- [ ] Apply migrations.
- [ ] Verify public docs and endpoints with cURL.
- [ ] Update README with the live API URL and reproducible instructions.

**Exit condition:** another person can clone, configure, run, test, and call the service without any AI dependency.

---

## 20. Definition of done

The capstone is complete only when all of these are true:

- [ ] A clean Git repository exists.
- [ ] A stranger can follow the README to run the application.
- [ ] FastAPI exposes documented REST endpoints.
- [ ] PostgreSQL persists CRUD data across restarts.
- [ ] Keycloak issues tokens and FastAPI verifies them correctly.
- [ ] `USER` and `ADMIN` permissions are enforced server-side.
- [ ] Users cannot access another user's records.
- [ ] At least one external API is integrated asynchronously.
- [ ] Validation, missing resources, upstream failures, and unexpected errors are handled.
- [ ] Automated tests cover core behavior and important failure paths.
- [ ] Configuration and secrets are handled through environment variables.
- [ ] Logging is useful and does not leak secrets.
- [ ] Docker packaging works.
- [ ] A publicly reachable deployment exists.
- [ ] The deployed API has been verified using OpenAPI and cURL or an API client.
- [ ] Meaningful generated changes were reviewed with Git diffs.
- [ ] The developer can explain the architecture and important code paths without an agent.
- [ ] One real coding-agent failure and the resulting engineering lesson are documented.

## 21. Interview explanation

A concise explanation you should be able to give:

> I built SpendWise, an expense-tracking REST API using FastAPI and PostgreSQL. Keycloak acts as the identity and authorization server: users authenticate with Keycloak, which issues signed JWT access tokens. The API verifies those tokens using Keycloak's JWKS, validates issuer and audience claims, and enforces role-based access control. Each expense is associated with the authenticated user's subject ID, so users can only access their own records. I used SQLAlchemy's async support for database access and HTTPX for an asynchronous currency-rate integration. The service includes validation, consistent error handling, automated tests, environment-based configuration, Docker packaging, and a public deployment.

You should be able to explain, in your own words:

1. Authentication vs authorization.
2. Why Keycloak is separate from FastAPI.
3. How JWT signature verification and JWKS work.
4. What `iss`, `aud`, `sub`, `exp`, and `kid` mean.
5. How role checks produce `403` while invalid authentication produces `401`.
6. How ownership checks prevent insecure direct object references (IDOR).
7. Why money uses `Decimal`.
8. Why the external API client needs timeouts and error mapping.
9. How Alembic migrations differ from creating tables at application startup.
10. How you tested the deployed service independently of your local environment.

---

## 22. Recommended first task

Start only with **Milestone 1**. Create the repository, get FastAPI responding, and bring up PostgreSQL and Keycloak with Docker Compose. Do not implement expense CRUD or JWT verification until the infrastructure is running and you can obtain a Keycloak access token.
