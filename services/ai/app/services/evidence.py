"""Evidence understanding service."""

import re

from app.providers.base import VisionProvider
from app.schemas.evidence import (
    EvidenceSignals,
    EvidenceUnderstandingRequest,
    EvidenceUnderstandingResult,
)


class EvidenceUnderstandingService:
    def __init__(self, vision: VisionProvider) -> None:
        self._vision = vision

    def understand(self, request: EvidenceUnderstandingRequest) -> EvidenceUnderstandingResult:
        text = f"{request.title} {request.description}".strip()
        metadata_location = request.metadata.get("location")
        location = str(metadata_location) if metadata_location else _find_location(text)

        # Get structured observations from vision provider
        vision_result = self._vision.describe(document_url=request.document_url, text_hint=text)

        # Combine vision-derived objects (certain + possible)
        vision_objects = vision_result.get("objects_certain", []) + vision_result.get(
            "objects_possible", []
        )

        # Combine vision-derived activities (certain + possible) with text-hint activities
        vision_activities = vision_result.get("activities_certain", []) + vision_result.get(
            "activities_possible", []
        )
        text_activities = _activities(text)

        # Merge activities, avoiding duplicates (case-insensitive)
        all_activities = vision_activities[:]
        for act in text_activities:
            if act.lower() not in [a.lower() for a in all_activities]:
                all_activities.append(act)

        objects = vision_objects
        activities = all_activities
        extracted_text = text or None

        # Confidence: backward-compatible heuristic.
        # Note: This is not a calibrated probability; it reflects signal presence only.
        confidence = 0.82 if extracted_text or objects or activities else 0.45

        return EvidenceUnderstandingResult(
            evidence_id=request.evidence_id,
            confidence=confidence,
            signals=EvidenceSignals(
                objects=objects,
                activities=activities,
                extracted_text=extracted_text,
                location=location,
                date=request.captured_at,
                other_signals={
                    "evidence_type": request.evidence_type,
                    "source": request.metadata.get("source"),
                    "tags": request.metadata.get("tags", []),
                    "original_filename": request.original_filename,
                    "mime_type": request.mime_type,
                },
            ),
        )


def _activities(text: str) -> list[str]:
    found: list[str] = []
    for keyword, label in [
        ("poured", "concrete poured"),
        ("pour", "concrete pour"),
        ("installed", "installed"),
        ("installation", "installation"),
        ("complete", "completed work"),
        ("delay", "delay"),
        ("extra", "additional work"),
        ("variation", "variation mentioned"),
    ]:
        if keyword in text.lower():
            found.append(label)
    return found


def _find_location(text: str) -> str | None:
    match = re.search(r"\b(level|l)\s*(\d+)\b", text, re.IGNORECASE)
    return f"Level {match.group(2)}" if match else None
