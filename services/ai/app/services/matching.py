"""Evidence-to-contract matching service."""

from app.schemas.common import Assessment
from app.schemas.matching import MatchingRequest, MatchingResult, MatchSuggestion
from app.services.text import tokens


class MatchingService:
    def match(self, request: MatchingRequest) -> MatchingResult:
        evidence_text = " ".join(
            [
                request.signals.extracted_text or "",
                request.signals.location or "",
                " ".join(request.signals.objects),
                " ".join(request.signals.activities),
            ]
        )
        evidence_tokens = set(tokens(evidence_text))
        scored = []
        for item in request.contract_items:
            item_tokens = tokens(f"{item.item_code} {item.description} {item.unit or ''}")
            hits = [token for token in item_tokens if token in evidence_tokens]
            score = len(hits) / len(item_tokens) if item_tokens else 0
            if score >= 0.25:
                scored.append((item, hits, score))

        scored.sort(key=lambda entry: entry[2], reverse=True)
        matches = [
            MatchSuggestion(
                contract_item_id=item.contract_item_id,
                confidence=round(0.4 + 0.55 * score, 2),
                assessment=_assessment(0.4 + 0.55 * score),
                reason=(
                    f"Evidence signals overlap with {item.item_code} {item.description}: "
                    f"{', '.join(hits)}."
                ),
                missing_evidence=_missing_evidence(0.4 + 0.55 * score),
            )
            for item, hits, score in scored[:3]
        ]
        return MatchingResult(evidence_id=request.evidence_id, matches=matches)


def _assessment(confidence: float) -> Assessment:
    if confidence >= 0.85:
        return "strong"
    if confidence >= 0.7:
        return "partial"
    return "weak"


def _missing_evidence(confidence: float) -> list[str]:
    if confidence >= 0.85:
        return []
    if confidence >= 0.7:
        return ["quantity confirmation"]
    return ["photo or docket confirming the work"]
