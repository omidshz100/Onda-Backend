from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.api.dependencies import DBSession
from app.schemas.common import HealthResponse

router = APIRouter(prefix="/health", tags=["system"])


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def readiness(db: DBSession) -> HealthResponse:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    return HealthResponse(status="ready")
