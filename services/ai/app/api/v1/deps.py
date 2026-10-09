"""Route dependencies for provider-backed AI services."""

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.providers.base import VisionProvider
from app.providers.mock import MockVisionProvider
from app.providers.openai import OpenAIVisionError, OpenAIVisionProvider
from app.providers.openrouter import OpenRouterVisionError, OpenRouterVisionProvider
from app.services.completeness import CompletenessService
from app.services.evidence import EvidenceUnderstandingService
from app.services.extraction import ContractExtractionService, MockExtractionProvider
from app.services.matching import MatchingService
from app.services.variations import VariationDetectionService


@lru_cache
def get_extraction_service() -> ContractExtractionService:
    return ContractExtractionService(MockExtractionProvider())


def get_vision_provider(settings: Settings = None) -> VisionProvider:
    """Create the appropriate vision provider based on configuration.

    This function is not cached because it depends on settings which are cached.
    The EvidenceUnderstandingService factory handles caching.
    """
    if settings is None:
        settings = get_settings()

    if settings.vision_provider == "openrouter":
        api_key = settings.openrouter_api_key.get_secret_value()
        if not api_key:
            raise OpenRouterVisionError(
                "AI_VISION_PROVIDER=openrouter but AI_OPENROUTER_API_KEY is not set"
            )
        return OpenRouterVisionProvider(
            api_key=api_key,
            base_url=settings.openrouter_base_url,
            model=settings.openrouter_model,
            timeout=settings.vision_timeout_seconds,
        )
    if settings.vision_provider == "openai":
        api_key = settings.openai_api_key.get_secret_value()
        if not api_key:
            raise OpenAIVisionError("AI_VISION_PROVIDER=openai but AI_OPENAI_API_KEY is not set")
        return OpenAIVisionProvider(
            api_key=api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            timeout=settings.vision_timeout_seconds,
        )
    return MockVisionProvider()


@lru_cache
def get_evision_service() -> EvidenceUnderstandingService:
    """Cached factory for EvidenceUnderstandingService with configured vision provider."""
    settings = get_settings()
    vision = get_vision_provider(settings)
    return EvidenceUnderstandingService(vision)


# Keep the old name for backward compatibility during transition
get_evidence_service = get_evision_service


@lru_cache
def get_matching_service() -> MatchingService:
    return MatchingService()


@lru_cache
def get_completeness_service() -> CompletenessService:
    return CompletenessService()


@lru_cache
def get_variation_service() -> VariationDetectionService:
    return VariationDetectionService()
