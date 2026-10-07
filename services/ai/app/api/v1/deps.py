"""Route dependencies for provider-backed AI services."""

from functools import lru_cache

from app.providers.mock import MockVisionProvider
from app.services.completeness import CompletenessService
from app.services.evidence import EvidenceUnderstandingService
from app.services.extraction import ContractExtractionService, MockExtractionProvider
from app.services.matching import MatchingService
from app.services.variations import VariationDetectionService


@lru_cache
def get_extraction_service() -> ContractExtractionService:
    return ContractExtractionService(MockExtractionProvider())


@lru_cache
def get_evidence_service() -> EvidenceUnderstandingService:
    return EvidenceUnderstandingService(MockVisionProvider())


@lru_cache
def get_matching_service() -> MatchingService:
    return MatchingService()


@lru_cache
def get_completeness_service() -> CompletenessService:
    return CompletenessService()


@lru_cache
def get_variation_service() -> VariationDetectionService:
    return VariationDetectionService()

