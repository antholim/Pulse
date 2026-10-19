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
