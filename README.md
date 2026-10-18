# PULSE

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
docker
```
