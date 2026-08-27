"""OCR 요청과 결과 모델.

작성자: 김진우
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

OCR_TYPE_HEALTH_CHECKUP = "HEALTH_CHECKUP"
OPERATION_EXTRACT = "EXTRACT"
OPERATION_CONFIRM_AND_SAVE = "CONFIRM_AND_SAVE"


@dataclass(frozen=True)
class MasterCheckupItem:
    """Supabase 건강검진 항목 마스터."""

    item_code: str
    item_name: str
    standard_unit: str | None


@dataclass(frozen=True)
class RawCheckupItem:
    """Gemini가 OCR 텍스트에서 추출한 원본 항목."""

    raw_name: str
    raw_value: str
    raw_unit: str | None = None
    printed_status: str | None = None


@dataclass(frozen=True)
class ParsedCheckupItem:
    """HEAPY 마스터에 연결된 건강검진 항목."""

    raw_name: str
    item_code: str | None
    item_name: str | None
    raw_value: str
    value: str
    unit: str | None
    printed_status: str | None
    confidence: float
    needs_review: bool


@dataclass(frozen=True)
class ExtractionResult:
    """사용자 확인 화면에 전달할 OCR 초안."""

    request_id: str
    ocr_type: str
    measured_at: str | None
    hospital_name: str | None
    items: tuple[ParsedCheckupItem, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConfirmedCheckup:
    """사용자가 확인한 Supabase 저장 입력."""

    measured_at: date
    items: tuple[ParsedCheckupItem, ...]
