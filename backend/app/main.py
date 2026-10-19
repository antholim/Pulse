from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import check_database
from sqlalchemy.exc import SQLAlchemyError

app = FastAPI(
    title="PULSE API",
    version="0.1.0",
    description="Backend API for the PULSE ecosystem platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "pulse-backend"}

@app.get("/health/db")
def database_health():
    try:
        check_database()
        return {"database": "connected"}
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )
