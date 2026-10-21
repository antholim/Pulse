# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

PULSE is a SOEN 490 capstone: a FastAPI + PostgreSQL backend and a React (Vite, TypeScript) frontend. The repo also holds internal team tooling (`discord-bots/`, `scripts/tickets/`) that is **not** part of the product.

## Repository layout

Three independent projects, each with its own dependencies and test setup:

| Path | Stack | Package manager |
| --- | --- | --- |
| `backend/` | Python 3.12 (pinned `<3.13`), FastAPI, SQLAlchemy 2, psycopg 3 | `uv` (`uv.lock`) |
| `frontend/` | Node 22 (`.nvmrc`), React 19, Vite, Vitest | `npm` (`package-lock.json`, use `npm ci`) |
| `discord-bots/team-bot/` | Python 3.12, discord.py, githubkit, SQLite | `pip install -e ".[dev]"` |

PULSE code must never import from `discord-bots/`.

## Commands

### Running locally

```bash
cp .env.example .env                         # then fill in the Postgres values
docker compose --profile full up --build     # db + backend :8000 (/docs) + frontend :5173
docker compose up db                         # only Postgres, run backend/frontend natively
```

### Backend (run from `backend/`)

```bash
uv sync
uv run uvicorn app.main:app --reload
uv run pytest                                # integration tests skip without TEST_DATABASE_URL
uv run pytest tests/core/test_security.py::test_name   # single test
uv run pytest --cov                          # fails under 50% (pyproject.toml)
uv run ruff check --fix . && uv run ruff format .
uv run alembic upgrade head                  # create/update the schema (DATABASE_URL)
uv run alembic revision --autogenerate -m "..."   # after a model change; review the file
uv run python -m app.seed                    # two demo tenants + mock sources, idempotent
```

Integration tests (`@pytest.mark.integration`, in `tests/integration/`) need a real Postgres:

```bash
docker compose --profile test up -d test-db  # port 5433, tmpfs, clean every start
TEST_DATABASE_URL=postgresql+psycopg://pulse_test:pulse_test@127.0.0.1:5433/pulse_test uv run pytest -m integration
```

On Windows use `127.0.0.1`, not `localhost`, in database URLs: compose binds IPv4 only and `localhost` tries `::1` first, which stalls every connection. If Application Control blocks `pytest.exe`/`alembic.exe`, use `uv run python -m pytest` / `python -m alembic`.

### Frontend (run from `frontend/`)

```bash
npm ci
npm run dev
npm test                                     # vitest run
npx vitest run src/services/api.test.ts      # single file (add -t "name" for one test)
npm run coverage                             # thresholds 50% in vite.config.ts
npm run lint                                 # --max-warnings=0
npm run format
npm run build                                # tsc -b && vite build
```

### Team bot (run from `discord-bots/team-bot/`)

```bash
pip install -e ".[dev]"
pytest --cov --cov-fail-under=90             # CI requires 90%
ruff check . && ruff format --check .
```

### Whole repo

```bash
pre-commit run --all-files    # what the CI Lint job runs; needs `npm ci` in frontend/ first
```

The pre-commit ESLint/Prettier hooks run the binaries in `frontend/node_modules`, so they fail if frontend deps aren't installed.

## Backend architecture

- `app/main.py` builds the FastAPI app, adds `CORSMiddleware` and `SecurityHeadersMiddleware`, and currently exposes only `/api/health` and `/health/db`.
- `app/core/database.py` loads the **repo-root** `.env` (not `backend/.env`). The engine and session factory are lazily created and `@cache`d so importing the app never requires `DATABASE_URL`; a missing URL raises `DatabaseNotConfiguredError` (surfaced as a 503). `get_db()` is the FastAPI session dependency. Tests that swap the DB must call `get_engine.cache_clear()` / `get_session_factory.cache_clear()` (see the `test_database` fixture in `tests/conftest.py`).
- `app/core/security.py`: `CORS_ORIGINS` is comma-separated and rejects `*` because credentials are allowed. Security headers are added with `setdefault`, so a route can override them.
- `app/models/` is data model v1 (#25; diagram and glossary in the wiki's "Overall Architecture and Class Diagrams" page). Every table except `tenant` has a non-null `tenant_id`, and every reference between tables is a composite FK on `(tenant_id, <id>)` to a `UNIQUE (tenant_id, id)`, so rows cannot point across tenants (D5). Build these with `same_tenant_fk()` in `app/models/base.py`; `tests/models/test_schema.py` fails if a table lacks `tenant_id`, a FK skips `tenant_id`, or a FK has no supporting index. `source_record` rows are versions: the current one has `valid_to IS NULL` (partial unique index `ux_source_record_current`), and versions of one record cannot overlap in time (`ex_source_record_versions_overlap`, needs `btree_gist`). `org_link` and `match_candidate` point at versions, so versioning must copy them to a new version. Allowed values (`kind`, `status`, ...) are CHECK constraints from tuples in the model modules; changing one needs a migration.
- Migrations live in `backend/migrations/` (Alembic, connection from `DATABASE_URL` via `get_engine()`); the integration fixture `migrated_database` upgrades to head and downgrades to base around each test, and `alembic check` runs in CI.
- The remaining packages (`ai`, `api`, `ingestion`, `processing`, `schemas`, `services`, `storage`) are empty scaffolding for the planned pipeline: ingest from the Omerlo API on a schedule → clean / normalize → entity resolution → snapshots. Follow this split when filling them in.
- `backend/synthetic/` generates deterministic, fully synthetic Omerlo data (`uv run python -m synthetic.omerlo_fixtures [--seed N --out DIR --schemas DIR]`) with deliberate duplicate organizations/people and a `ground_truth.dev_only.json` for entity-resolution development. `omerlo_schema.py` holds strict Pydantic models (unknown fields fail). Output in `synthetic/out/` is git-ignored. Both `app` and `synthetic` count toward coverage.
- **Data rule (Quebec Law 25):** real client data never goes into the repo or into AI tools. Use the synthetic generator for dev/tests/demos.

Tests mirror source layout: `backend/tests/core/` tests `backend/app/core/`; frontend tests sit next to the file they test (`*.test.tsx`). New tests mark their sections with `# Arrange`, `# Act` and `# Assert` comments (a single `# Act / Assert` when the call and the check are one statement).

## Frontend

`src/services/api.ts` is the API client; base URL comes from `VITE_API_URL` (default `http://localhost:8000`). Vitest uses jsdom with `src/test/setup.ts`.

## Team bot architecture

Logic lives in `domain/`, `services/` and `formatting.py` (testable without Discord); `cogs/` stay thin. Each scheduled job is a cog method returning what it posted, called by both its `tasks.loop` and a `/run` subcommand in `cogs/run.py`. To add a command: new cog with async `setup(bot)`, add it to `EXTENSIONS` in `bot.py`, give every command a `description`, and add the cog class to `HELP_SECTIONS` in `formatting.py` (a test enforces both). It deploys to Fly.io from CI on pushes to `main`.

## Style and conventions

- Ruff: line length 100, py312, rules `E,F,W,I,B,UP,SIM,RUF` (root `ruff.toml` plus per-project config). Prettier + ESLint for the frontend. `.editorconfig`: LF, 2 spaces (4 for Python).
- Branches are `feature/<issue>-<slug>` / `fix/<slug>`; commit messages are short imperative sentences ending with the issue number, e.g. `Add security headers and configurable CORS origins (#22)`, optionally with a `feat:` / `fix:` / `test:` / `docs:` prefix.
- PRs use `.github/pull_request_template.md`, which requires `Closes #N` and an **"AI assistance"** section (SOEN 490 requirement).
- Before writing a commit, PR or issue, read `docs/writing-prs-and-issues.md`: small commits, the existing PR format, short code comments with no issue numbers, no AI-sounding wording, and never a `Co-Authored-By` trailer or "Generated with" footer.
- Backlog issues are generated from `scripts/tickets/data.py` via `python build.py` (dry run) / `--apply`; always commit `state.json` afterwards and never delete it. No em or en dashes in ticket text.
