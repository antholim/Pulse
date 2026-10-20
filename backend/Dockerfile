
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Keep the virtual environment outside the app directory
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy dependency definitions first
COPY pyproject.toml uv.lock ./

# Install production dependencies
RUN uv sync --locked --no-dev --no-install-project

# Copy FastAPI application and database migrations
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8000

CMD ["uvicorn", "app.main:app", \
    "--host", "0.0.0.0", "--port", "8000"]
