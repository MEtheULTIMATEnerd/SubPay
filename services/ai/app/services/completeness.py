"""Evidence support completeness service."""

from app.schemas.common import CompletenessStatus
from app.schemas.completeness import CompletenessRequest, CompletenessResult


class CompletenessService:
    def assess(self, request: CompletenessRequest) -> CompletenessResult:
        if not request.matches:
            return CompletenessResult(
                contract_item_id=request.contract_item_id,
                status="missing",
                confidence=0.9,
                reason="No supporting evidence suggestions were supplied for this contract item.",
            )
        ordered = sorted(request.matches, key=lambda match: match.confidence, reverse=True)
        best = ordered[0]
        status = _status(best.assessment, bool(best.missing_evidence))
        return CompletenessResult(
            contract_item_id=request.contract_item_id,
            status=status,
            confidence=best.confidence,
            reason=(
                "Evidence support is based on the strongest AI suggestion. "
                f"Best assessment: {best.assessment}."
            ),
        )


def _status(assessment: str, has_missing_evidence: bool) -> CompletenessStatus:
    if assessment == "strong" and not has_missing_evidence:
        return "strong"
    if assessment in {"strong", "partial"}:
        return "partial"
    return "weak"
