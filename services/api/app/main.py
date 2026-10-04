"""SubPay API entrypoint.

Run locally:  uvicorn app.main:app --reload --port 8000
API docs:     http://localhost:8000/api/v1/docs
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.limits import BodySizeLimitMiddleware

logger = logging.getLogger("subpay.api")

DESCRIPTION = """
Application API for SubPay: verified progress claims, from site photo to payment.

All endpoints except `/health` need `Authorization: Bearer <Supabase access token>`.
The signed-in user and their organisation are always derived from that token.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()
        override = None
    else:
        override = settings

    prefix = settings.api_v1_prefix
    app = FastAPI(
        title="SubPay API",
        version=settings.version,
        description=DESCRIPTION,
        docs_url=f"{prefix}/docs",
        openapi_url=f"{prefix}/openapi.json",
        redoc_url=None,
    )
    if override is not None:
        app.dependency_overrides[get_settings] = lambda: override

    # Added before CORS so that CORS wraps it and a 413 still carries CORS headers.
    app.add_middleware(BodySizeLimitMiddleware)
    # Bearer tokens, not cookies, so credentials stay off and origins stay explicit.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    register_error_handlers(app)
    app.include_router(api_router, prefix=prefix)

    if not settings.supabase_jwks_url and not settings.supabase_jwt_secret.get_secret_value():
        logger.warning(
            "No SUPABASE_URL or SUPABASE_JWT_SECRET configured: "
            "every authenticated request will be rejected."
        )

    return app


app = create_app()
