from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import DatabaseNotConfiguredError, check_database
from app.core.logging import configure_logging, get_logger
from app.core.request_context import RequestContextMiddleware
from app.core.security import SecurityHeadersMiddleware, cors_origins

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(api: FastAPI) -> AsyncIterator[None]:
    logger.info("app_startup", version=api.version)
    yield
    logger.info("app_shutdown")


app = FastAPI(
    title="PULSE API",
    version="0.1.0",
    description="Backend API for the PULSE ecosystem platform.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    # QUERY is the new safe, body-carrying read method (IETF draft "The HTTP QUERY Method").
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "QUERY"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(SecurityHeadersMiddleware)
# Added last so it wraps the other middleware and every response carries the request id.
app.add_middleware(RequestContextMiddleware)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "pulse-backend"}


@app.get("/health/db")
def database_health():
    try:
        check_database()
        return {"database": "connected"}
    except (SQLAlchemyError, DatabaseNotConfiguredError) as err:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from err
