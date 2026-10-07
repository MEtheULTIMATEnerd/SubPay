"""Potential variation detection service."""

import re

from app.schemas.variations import VariationDetectionRequest, VariationDetectionResult

_CHANGE_WORDS = re.compile(
    r"\b(additional|extra|latent|unforeseen|changed|not on (the )?drawings|variation|instructed)\b",
    re.IGNORECASE,
)


class VariationDetectionService:
    def detect(self, request: VariationDetectionRequest) -> VariationDetectionResult:
        text = " ".join(
            [
                request.signals.extracted_text or "",
                " ".join(request.signals.activities),
                " ".join(request.signals.objects),
            ]
        )
        best_confidence = max((match.confidence for match in request.matches), default=0)
        flag = best_confidence < 0.85 and bool(_CHANGE_WORDS.search(text))
        return VariationDetectionResult(
            potential_variation=flag,
            confidence=0.72 if flag else 0.5,
            reason=(
                "Evidence describes additional or changed work with no strong "
                "matching contract line."
                if flag
                else "No potential variation language was detected, or a strong "
                "contract match exists."
            ),
            related_evidence_ids=[request.evidence_id] if flag else [],
            review_required=flag,
        )
