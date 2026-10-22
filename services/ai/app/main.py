"""SubPay AI FastAPI application."""

from fastapi import FastAPI

from app.api.v1.router import router as ai_v1_router
from app.core.config import get_settings
from app.local_vision import router as local_vision_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SubPay AI Service",
        version=settings.version,
        description="AI/intelligence boundary for contract extraction and evidence analysis.",
    )
    app.include_router(ai_v1_router)
    app.include_router(local_vision_router)
    return app


app = create_app()
