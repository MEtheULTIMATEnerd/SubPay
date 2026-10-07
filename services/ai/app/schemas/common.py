"""Shared AI schema primitives."""

from typing import Literal

from pydantic import BaseModel, Field

Assessment = Literal["strong", "partial", "weak"]
CompletenessStatus = Literal["strong", "partial", "weak", "missing"]


class ConfidenceMixin(BaseModel):
    """A bounded confidence score. It is not a legal or payment assessment."""

    confidence: float = Field(ge=0, le=1)

