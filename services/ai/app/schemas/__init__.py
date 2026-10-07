"""Pydantic schemas for the AI service boundary."""

from app.schemas.common import Assessment, CompletenessStatus
from app.schemas.completeness import CompletenessRequest, CompletenessResult
from app.schemas.evidence import (
    EvidenceSignals,
    EvidenceUnderstandingRequest,
    EvidenceUnderstandingResult,
)
from app.schemas.extraction import ExtractedContractItem, ExtractionRequest, ExtractionResult
from app.schemas.matching import (
    MatchingContractItem,
    MatchingRequest,
    MatchingResult,
    MatchSuggestion,
)
from app.schemas.variations import VariationDetectionRequest, VariationDetectionResult

__all__ = [
    "Assessment",
    "CompletenessRequest",
    "CompletenessResult",
    "CompletenessStatus",
    "EvidenceSignals",
    "EvidenceUnderstandingRequest",
    "EvidenceUnderstandingResult",
    "ExtractedContractItem",
    "ExtractionRequest",
    "ExtractionResult",
    "MatchSuggestion",
    "MatchingContractItem",
    "MatchingRequest",
    "MatchingResult",
    "VariationDetectionRequest",
    "VariationDetectionResult",
]
