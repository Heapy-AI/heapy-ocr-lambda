"""OCR 요청과 결과 모델.

작성자: 김진우
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

OCR_TYPE_HEALTH_CHECKUP = "HEALTH_CHECKUP"
OCR_TYPE_MEDICATION = "MEDICATION"
OPERATION_EXTRACT = "EXTRACT"
OPERATION_OCR_PAGE = "OCR_PAGE"
OPERATION_PARSE = "PARSE"


@dataclass(frozen=True)
class MasterCheckupItem:
    """내부 건강검진 항목 마스터."""

    item_code: str
    item_name: str
    standard_unit: str | None


@dataclass(frozen=True)
class RawCheckupItem:
    """파서가 OCR 텍스트에서 추출한 원본 항목."""

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
    parser_mode: str = "unknown"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        normalized_results = [
            {
                "item_code": item.item_code,
                "value": item.value,
                "status": item.printed_status,
            }
            for item in self.items
            if item.item_code is not None
        ]
        result["normalized"] = {
            "measured_at": self.measured_at,
            "results": normalized_results,
            "ready": self.measured_at is not None and bool(normalized_results),
        }
        return result


@dataclass(frozen=True)
class ParsedMedication:
    """약봉투에서 인식한 약 한 종류의 복용 정보."""

    raw_name: str
    medicine_name: str
    strength: str | None
    dose_per_intake: str | None
    dose_unit: str | None
    frequency_per_day: int | None
    duration_days: int | None
    timing_labels: tuple[str, ...] = field(default_factory=tuple)
    meal_relation: str | None = None
    administration_note: str | None = None


@dataclass(frozen=True)
class MedicationExtractionResult:
    """사용자 확인 화면에 전달할 약봉투 OCR 초안."""

    request_id: str
    ocr_type: str
    prescribed_at: str | None
    dispensed_at: str | None
    medical_institution_name: str | None
    pharmacy_name: str | None
    medications: tuple[ParsedMedication, ...]
    parser_mode: str = "gemini"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["normalized"] = {
            "prescribed_at": self.prescribed_at,
            "dispensed_at": self.dispensed_at,
            "medical_institution_name": self.medical_institution_name,
            "pharmacy_name": self.pharmacy_name,
            "medications": [asdict(medication) for medication in self.medications],
            "ready": bool(self.medications),
        }
        return result
