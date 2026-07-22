# RFQ Agent — Authentication Service

A production-style **login & registration** feature for the RFQ Agent platform,
built with **FastAPI**. It exposes both a **JSON API** (for programmatic clients)
and **server-rendered HTML pages** (login, register, dashboard), backed by a
relational database, JWT access tokens, and bcrypt password hashing.

The codebase follows the layered architecture and coding standards defined in
[`coding_standards_documents/`](./coding_standards_documents): a single
installable package under `src/`, one responsibility per module, OOP design
patterns, full type hints, Google-style docstrings, `pydantic-settings` for
configuration, and structured logging.

---

## Table of contents

- [Features](#features)
- [Architecture & design patterns](#architecture--design-patterns)
- [Project structure](#project-structure)
- [Endpoints](#endpoints)
- [Configuration](#configuration)
- [Run with Docker (recommended)](#run-with-docker-recommended)
- [Run manually (local Python)](#run-manually-local-python)
- [Using the app](#using-the-app)
- [Development: tests, lint, types](#development-tests-lint-types)
- [Make targets](#make-targets)

---

## Features

- **Register** a user (email, full name, password) — via JSON API or HTML form.
- **Login** returning a signed **JWT access token** (API) or an **HttpOnly
  session cookie** (HTML pages).
- **Protected routes**: `GET /api/v1/auth/me` (Bearer token) and `/dashboard`
  (cookie), both reject unauthenticated access.
- **Secure password storage** with bcrypt (salted, configurable work factor).
- **Interactive API docs** at `/docs` (Swagger UI) and `/redoc`.
- **Health probe** at `/health` for containers/orchestrators.
- Works on **SQLite** (zero setup, for local/manual runs) or **PostgreSQL**
  (used by the Docker stack) — chosen entirely via `DATABASE_URL`.

## Architecture & design patterns

The feature is split into clean layers, each with a single job:

| Layer | Location | Responsibility |
|---|---|---|
| **Config** | `config/settings.py` | Typed, env-driven settings (`pydantic-settings`) |
| **Domain** | `domain/` | ORM models, enums, and Pydantic request/response schemas |
| **Integrations** | `integrations/database.py` | SQLAlchemy engine & session management |
| **Services** | `services/` | Business logic — the parts worth unit-testing |
| **API** | `api/` | Thin FastAPI layer: routes, dependencies, app factory |
| **Observability** | `observability/logging.py` | Central structured logger |

Design patterns applied:

- **Factory** — `create_app()` builds the FastAPI instance; `Database` builds the engine/sessions.
- **Repository** — `UserRepository` isolates all user persistence behind an interface.
- **Strategy** — `PasswordHasher` (abstract) with a `BcryptPasswordHasher` implementation, so the hashing algorithm can be swapped without touching callers.
- **Service / orchestration** — `AuthService` coordinates the repository, hasher, and token service.
- **Dependency Injection** — FastAPI `Depends` wires request-scoped sessions and services (`api/deps.py`).
- **Singleton** — cached `Settings` and shared `Database` instance.

## Project structure

```
RFQAgent/
├── Dockerfile                 # application image (uvicorn + FastAPI)
├── docker-compose.yml         # app + PostgreSQL for local orchestration
├── Makefile                   # dev & container workflow (run `make help`)
├── pyproject.toml             # deps, build system, ruff/mypy/pytest config
├── .env.example               # documents every environment variable
├── main.py                    # convenience entry point (python main.py)
├── src/                        # the importable application package (import src.*)
│   ├── config/settings.py     # pydantic-settings configuration
│   ├── domain/
│   │   ├── enums.py           # UserRole, TokenType
│   │   ├── models.py          # SQLAlchemy User model
│   │   └── schemas/           # UserCreate, UserRead, LoginRequest, TokenResponse
│   ├── integrations/database.py
│   ├── services/
│   │   ├── password_hasher.py # Strategy pattern (bcrypt)
│   │   ├── token_service.py   # JWT encode/decode
│   │   ├── user_repository.py # Repository pattern
│   │   ├── auth_service.py    # orchestration
│   │   └── exceptions.py      # typed domain errors
│   ├── api/
│   │   ├── main.py            # create_app() factory + /health
│   │   ├── deps.py            # DI: session, services, current user
│   │   ├── templating.py      # Jinja2 environment
│   │   └── routes/
│   │       ├── auth.py        # JSON API: /register /login /me
│   │       └── pages.py       # HTML: /login /register /dashboard /logout
│   └── observability/logging.py
├── templates/                 # Jinja2 HTML (base, login, register, dashboard)
├── static/css/styles.css      # page styling
└── tests/unit/                # pytest suite (services)
```

## Endpoints

### JSON API (prefix `/api/v1/auth`)

| Method | Path | Body | Success | Description |
|---|---|---|---|---|
| `POST` | `/register` | `{email, full_name, password}` | `201` `UserRead` | Create an account |
| `POST` | `/login` | `{email, password}` | `200` `TokenResponse` | Get a JWT access token |
| `GET`  | `/me` | — (Bearer token) | `200` `UserRead` | Current authenticated user |

### HTML pages

| Method | Path | Description |
|---|---|---|
| `GET`  | `/` | Redirects to `/dashboard` (if signed in) or `/login` |
| `GET`/`POST` | `/login` | Login form; on success sets an HttpOnly cookie |
| `GET`/`POST` | `/register` | Registration form |
| `GET`  | `/dashboard` | Protected page showing the current user |
| `GET`  | `/logout` | Clears the session cookie |

### System

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness/readiness probe |
| `GET` | `/docs`, `/redoc` | Interactive API documentation |

## Configuration

All configuration comes from environment variables (or a `.env` file). Copy the
template and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` or `production` (controls cookie `Secure` flag) |
| `DEBUG` | `true` | Enables autoreload / verbose behaviour |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | ASGI bind address |
| `DATABASE_URL` | `sqlite:///./data/rfq_agent.db` | SQLAlchemy connection URL |
| `JWT_SECRET_KEY` | *(insecure placeholder)* | **Override in production** with a long random value |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access-token lifetime |
| `SESSION_COOKIE_NAME` | `rfq_access_token` | Cookie holding the token for HTML pages |
| `LOG_LEVEL` | `INFO` | Logging level |

Generate a strong secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> **Never commit a real `.env`.** It is git-ignored; `.env.example` documents the keys.

---

## Run with Docker (recommended)

This runs the **full stack**: the FastAPI app **plus a PostgreSQL database**,
wired together automatically. Requires Docker with the Compose v2 plugin.

### Quick start (via Makefile)

```bash
make docker-up      # build images and start app + PostgreSQL in the background
```

Then open **http://localhost:8000** (docs at **http://localhost:8000/docs**).

Other useful commands:

```bash
make docker-logs    # follow the application logs
make docker-down    # stop and remove the containers
make docker-restart # rebuild and restart
make docker-shell   # open a shell inside the app container
```

### Quick start (raw docker compose)

If you prefer not to use `make`:

```bash
docker compose up --build -d     # start
docker compose logs -f app       # logs
docker compose down              # stop
docker compose down -v           # stop and delete the database volume
```

Notes:

- The app waits for PostgreSQL to become healthy before starting (and also
  retries the initial connection), so a clean `up` is reliable.
- PostgreSQL data persists in the `pgdata` Docker volume across restarts.
- The database port is **not** published to the host by default (to avoid
  clashing with a local PostgreSQL). To inspect it from the host, uncomment the
  `ports` block under the `db` service in `docker-compose.yml`.
- To use your own secrets, create a `.env` file (see [Configuration](#configuration));
  Compose picks it up automatically.

---

## Run manually (local Python)

For local development without Docker. Uses **SQLite** by default, so there is
**no database to install**. Requires Python 3.12+ and
[`uv`](https://docs.astral.sh/uv/) (a fast Python package manager).

### With `uv` (recommended)

```bash
# 1. Install dependencies (creates a .venv automatically)
make install                 # equivalent to: uv sync --extra dev

# 2. (optional) create your .env
cp .env.example .env

# 3. Run the server with autoreload
make run                     # equivalent to: uv run uvicorn src.api.main:app --reload
```

Open **http://localhost:8000**.

### With plain `pip` / `venv`

If you don't have `uv`:

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -e ".[dev]"             # installs the package + dev tools

uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
# or simply:
python main.py
```

The SQLite database file is created automatically at `./data/rfq_agent.db` on
first run.

### Point manual runs at PostgreSQL (optional)

```bash
export DATABASE_URL="postgresql+psycopg2://rfq:rfq@localhost:5432/rfq"
make run
```

---

## Using the app

**In the browser:** visit http://localhost:8000 → you'll be sent to the login
page → click *Create one* to register → sign in → you land on the dashboard →
*Sign out* clears your session.

**Via the API** (using `curl`):

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","full_name":"Ada Lovelace","password":"password123"}'

# Login -> capture the token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","password":"password123"}' | \
  python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Call a protected endpoint
curl http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"
```

---

## Development: tests, lint, types

```bash
make test        # run the pytest unit suite
make lint        # ruff lint
make format      # ruff auto-format
make typecheck   # mypy --strict
make check       # lint + typecheck + tests (the CI gate)
```

Tests run against an in-memory SQLite database and mock nothing external, so
they are fast and deterministic.

## Make targets

Run `make` or `make help` to see everything:

| Target | Description |
|---|---|
| `install` | Create the virtualenv and install all deps (incl. dev) |
| `run` | Run the app locally with autoreload |
| `test` | Run the unit test suite |
| `lint` / `format` / `typecheck` | Code quality tooling |
| `check` | lint + typecheck + tests |
| `docker-build` | Build the application image |
| `docker-up` | Build & start the full stack (app + PostgreSQL) |
| `docker-down` | Stop and remove containers |
| `docker-restart` | Rebuild and restart |
| `docker-logs` | Follow application logs |
| `docker-shell` | Shell into the running app container |
| `clean` | Remove caches, build artifacts and the local SQLite DB |
