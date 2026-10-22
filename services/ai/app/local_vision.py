"""Opt-in loopback bridge delegating to the existing OpenAI provider."""

import base64
import secrets
from ipaddress import ip_address

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings, get_settings
from app.providers.openai import OpenAIVisionProvider

router = APIRouter()


class InlineImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_url: str = Field(max_length=14_000_000)


@router.post("/ai/v1/local/vision")
def observe(body: InlineImage, request: Request, settings: Settings = Depends(get_settings)):
    if not settings.local_vision_enabled:
        raise HTTPException(404, "Local vision disabled")
    token = settings.local_access_token.get_secret_value()
    try:
        loopback = bool(request.client and ip_address(request.client.host).is_loopback)
    except ValueError:
        loopback = False
    auth = request.headers.get("authorization", "")
    if (
        not loopback
        or len(token) < 32
        or not secrets.compare_digest(auth.encode(), f"Bearer {token}".encode())
    ):
        raise HTTPException(403, "Local vision access denied")
    if settings.vision_provider != "openai":
        raise HTTPException(503, "OpenAI must be explicitly selected")
    prefix, sep, encoded = body.document_url.partition(",")
    if not sep or prefix not in {f"data:image/{t};base64" for t in ("jpeg", "png", "webp")}:
        raise HTTPException(422, "Inline image required")
    try:
        data = base64.b64decode(encoded, validate=True)
        if not data or len(data) > 10 * 1024 * 1024:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "Invalid inline image") from None
    try:
        with OpenAIVisionProvider(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            timeout=settings.vision_timeout_seconds,
            strict_response=True,
            image_detail="low",
        ) as provider:
            observations = provider.describe(document_url=body.document_url)
    except Exception:
        raise HTTPException(502, "Vision provider failed; no fallback") from None
    return {"provider": "openai", "model": settings.openai_model, "observations": observations}
