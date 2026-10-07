"""Contract extraction service."""

import re
from typing import Protocol

from app.schemas.extraction import ExtractedContractItem, ExtractionRequest, ExtractionResult


class ExtractionProvider(Protocol):
    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...


_Row = tuple[str, str, float | None, str | None, float | None, float | None, float, str | None]

_FITOUT_SCHEDULE: list[_Row] = [
    ("4.2", "Electrical conduit installation", 120, "m", 45, 5400, 0.91, None),
    ("4.3", "Cable tray installation", 80, "m", 60, 4800, 0.88, None),
    (
        "4.5",
        "Switchboard installation",
        1,
        "item",
        12500,
        12500,
        0.84,
        "Notify builder 5 days before energisation",
    ),
    ("6.1", "Lighting fit-off", None, None, None, 7600, 0.67, None),
]

_FORMWORK_SCHEDULE: list[_Row] = [
    ("1.1", "Preliminaries and site establishment", 1, "item", 4500, 4500, 0.82, None),
    ("2.1", "Formwork, slab edges", 180, "m²", 75, 13500, 0.90, None),
    ("2.2", "Formwork, columns", 96, "m²", 95, 9120, 0.87, None),
    (
        "3.1",
        "Concrete supply and place",
        110,
        "m³",
        245,
        26950,
        0.86,
        "Notify builder 48 hours before each pour",
    ),
    (
        "5.4",
        "Delay costs, standing time",
        None,
        "hr",
        None,
        None,
        0.55,
        "Written direction required within 5 business days",
    ),
]


class MockExtractionProvider:
    """Deterministic extraction provider for Phase A."""

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        is_fitout = re.search(r"fitout|electrical", request.original_filename, re.IGNORECASE)
        schedule = _FITOUT_SCHEDULE if is_fitout else _FORMWORK_SCHEDULE
        return ExtractionResult(
            contract_id=request.contract_id,
            items=[
                ExtractedContractItem(
                    item_code=code,
                    description=description,
                    quantity=quantity,
                    unit=unit,
                    rate=rate,
                    amount=amount,
                    notice_requirement=notice,
                    confidence=confidence,
                    source_reference=f"Schedule of rates, item {code}",
                )
                for code, description, quantity, unit, rate, amount, confidence, notice in schedule
            ],
        )


class ContractExtractionService:
    def __init__(self, provider: ExtractionProvider) -> None:
        self._provider = provider

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        return self._provider.extract(request)
