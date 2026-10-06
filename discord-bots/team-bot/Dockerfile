FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/team-bot.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --create-home bot \
    && mkdir -p /data && chown bot /data

USER bot
# Keep the SQLite file on a volume so it survives restarts and redeploys.
VOLUME ["/data"]
CMD ["python", "-m", "team_bot"]
