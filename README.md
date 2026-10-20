# PULSE

[![CI](https://github.com/antholim/Pulse/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/antholim/Pulse/actions/workflows/ci.yml)

SOEN 490 Capstone Project

## Local development with Docker

### Prerequisites

- Docker Desktop with Docker Engine running
- Git
- uv (only required when running the backend outside Docker)

### Environment configuration

Create a local `.env` file at the root of the repository using `.env.example` as a template:

```bash
cp .env.example .env
```

Configure the PostgreSQL environment variables in `.env`. This file is excluded from Git.

### Starting PULSE

From the root of the repository, run:

```bash
docker compose --profile full up --build
```

Docker Compose builds and starts the following services:

| Service                   | Address                    |
| ------------------------- | -------------------------- |
| React frontend            | http://localhost:5173      |
| FastAPI backend           | http://localhost:8000      |
| FastAPI API documentation | http://localhost:8000/docs |
| PostgreSQL                | localhost:5432             |

To run only PostgreSQL while developing the frontend and backend locally:

```bash
docker compose up db
```

### Database schema

The schema is created by Alembic migrations in `backend/migrations/`, from the models in `backend/app/models/`. A fresh database is empty until you run them:

```bash
cd backend
uv run alembic upgrade head          # create or update the tables
uv run python -m app.seed            # two demo tenants with a mock source each (safe to rerun)

# With the Docker stack running instead:
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.seed
```

After changing a model, generate a migration, read it, and adjust it before committing:

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic downgrade -1          # undo the last migration
```

CI fails when the models and the migrations disagree (`alembic check` in `tests/integration/test_migrations.py`).

## Logging and errors

The backend writes one JSON object per line to stdout, with `timestamp`, `level`, `module`, `event` and a `request_id` (API requests) or `run_id` (syncs and imports). Set the level with `LOG_LEVEL` (`DEBUG`, `INFO`, `WARN`, `ERROR`; default `INFO`). Emails, phone numbers and secrets are masked.

Every API response carries an `X-Request-ID` header, and every error response has the same body:

```json
{"error": {"code": "not_found", "message": "Organization 7 not found", "details": null, "request_id": "5a52f95c..."}}
```

The frontend logs through `src/services/logger.ts` (`VITE_LOG_LEVEL`, default `debug` in development and `warn` in builds); ESLint rejects direct `console` calls. See the wiki page [Logging & Error Handling](https://github.com/antholim/Pulse/wiki/Logging-&-Error-Handling).

## Code style

| Area                    | Linter | Formatter | Config                                  |
| ----------------------- | ------ | --------- | --------------------------------------- |
| Backend and Python code | Ruff   | Ruff      | `backend/pyproject.toml`, `ruff.toml`   |
| Frontend                | ESLint | Prettier  | `frontend/eslint.config.js`, `frontend/.prettierrc.json` |

Editor-wide settings (indentation, line endings) live in `.editorconfig`. VS Code and Cursor will suggest the matching extensions from `.vscode/extensions.json`.

### One-time setup

```bash
pip install pre-commit
pre-commit install
cd backend && uv sync
cd ../frontend && npm ci
```

After this, every `git commit` formats and lints the staged files automatically. If a hook changes a file, review the change, `git add` it and commit again.

### Running the checks manually

```bash
pre-commit run --all-files          # everything

cd backend
uv run ruff check --fix .           # lint
uv run ruff format .                # format

cd frontend
npm run lint
npm run format
```

## Tests

| Area     | Framework                     | Mocking                         | Coverage                    |
| -------- | ----------------------------- | ------------------------------- | --------------------------- |
| Backend  | pytest                        | pytest-mock, respx (HTTP calls) | pytest-cov, branch coverage |
| Frontend | Vitest, React Testing Library | Vitest (`vi.mock`, `vi.fn`)     | Vitest with v8              |

Tests mirror the source layout: `backend/tests/core/` tests `backend/app/core/`, and frontend tests sit next to the file they test (`App.test.tsx`). Coverage must stay above 50 percent; core logic modules aim for 80 percent.

```bash
cd backend
uv run pytest                       # unit tests; integration tests are skipped
uv run pytest --cov                 # with the coverage report

cd frontend
npm test                            # all tests once
npm run test:watch                  # rerun on change
npm run coverage                    # with the coverage report
```

### Integration tests

Backend tests marked `integration` (in `backend/tests/integration/`) run against a real PostgreSQL. They are skipped unless `TEST_DATABASE_URL` is set:

```bash
docker compose --profile test up -d test-db
cd backend
TEST_DATABASE_URL=postgresql+psycopg://pulse_test:pulse_test@localhost:5433/pulse_test uv run pytest -m integration
```

The `test-db` service keeps its data in memory, so every start is a clean database.
