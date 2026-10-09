"""Routes for the documented `/ai/v1` boundary."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import (
    get_completeness_service,
    get_evidence_service,
    get_extraction_service,
    get_matching_service,
    get_variation_service,
)
from app.core.config import Settings, get_settings
from app.schemas.completeness import CompletenessRequest, CompletenessResult
from app.schemas.evidence import EvidenceUnderstandingRequest, EvidenceUnderstandingResult
from app.schemas.extraction import ExtractionRequest, ExtractionResult
from app.schemas.matching import MatchingRequest, MatchingResult
from app.schemas.variations import VariationDetectionRequest, VariationDetectionResult
from app.services.completeness import CompletenessService
from app.services.evidence import EvidenceUnderstandingService
from app.services.extraction import ContractExtractionService
from app.services.matching import MatchingService
from app.services.variations import VariationDetectionService

router = APIRouter(prefix="/ai/v1")


@router.get("/health", tags=["health"])
def health(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "status": "ok",
        "service": "subpay-ai",
        "version": settings.version,
        "environment": settings.environment,
        "vision_provider": settings.vision_provider,
    }


@router.post(
    "/contracts/{contract_id}/extract",
    response_model=ExtractionResult,
    tags=["contracts"],
)
def extract_contract(
    contract_id: UUID,
    body: ExtractionRequest,
    service: ContractExtractionService = Depends(get_extraction_service),
) -> ExtractionResult:
    request = body.model_copy(update={"contract_id": contract_id})
    return service.extract(request)


@router.post(
    "/evidence/{evidence_id}/understand",
    response_model=EvidenceUnderstandingResult,
    tags=["evidence"],
)
def understand_evidence(
    evidence_id: UUID,
    body: EvidenceUnderstandingRequest,
    service: EvidenceUnderstandingService = Depends(get_evidence_service),
) -> EvidenceUnderstandingResult:
    request = body.model_copy(update={"evidence_id": evidence_id})
    return service.understand(request)


@router.post("/matches", response_model=MatchingResult, tags=["matching"])
def match_evidence(
    body: MatchingRequest,
    service: MatchingService = Depends(get_matching_service),
) -> MatchingResult:
    return service.match(body)


@router.post("/completeness", response_model=CompletenessResult, tags=["completeness"])
def assess_completeness(
    body: CompletenessRequest,
    service: CompletenessService = Depends(get_completeness_service),
) -> CompletenessResult:
    return service.assess(body)


@router.post(
    "/variations/detect",
    response_model=VariationDetectionResult,
    tags=["variations"],
)
def detect_variation(
    body: VariationDetectionRequest,
    service: VariationDetectionService = Depends(get_variation_service),
) -> VariationDetectionResult:
    return service.detect(body)
