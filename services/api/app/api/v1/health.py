from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(tags=["platform"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Confirms the API process is running. Requires no authentication."""
    return HealthResponse(
        status="ok",
        service="subpay-api",
        version=settings.version,
        environment=settings.environment,
    )
