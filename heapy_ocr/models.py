"""OCR 요청과 결과 모델.

작성자: 김진우
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from heapy_ocr.findings import Finding

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
    value_type: str = "numeric"
    is_active: bool = True


@dataclass(frozen=True)
class RawCheckupItem:
    """파서가 OCR 텍스트에서 추출한 원본 항목."""

    raw_name: str
    raw_value: str
    raw_unit: str | None = None
    printed_status: str | None = None
    source_page: int | None = None
    detail_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedCheckupItem:
    """HEAPY 마스터에 연결된 건강검진 항목."""

    raw_name: str
    item_code: str | None
    item_name: str | None
    raw_value: str
    value: str
    raw_unit: str | None
    unit: str | None
    printed_status: str | None
    source_page: int | None
    detail_data: dict[str, Any]
    confidence: float
    needs_review: bool


@dataclass(frozen=True)
class CheckupSummary:
    """문서에 인쇄된 종합 판정과 권고를 보존한다."""

    overall_status: str | None = None
    suspected_diseases: tuple[str, ...] = field(default_factory=tuple)
    diagnosed_diseases: tuple[str, ...] = field(default_factory=tuple)
    lifestyle_recommendations: tuple[str, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)
    risk_assessments: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "suspected_diseases": list(self.suspected_diseases),
            "diagnosed_diseases": list(self.diagnosed_diseases),
            "lifestyle_recommendations": list(self.lifestyle_recommendations),
            "recommendations": list(self.recommendations),
            "risk_assessments": list(self.risk_assessments),
        }


@dataclass(frozen=True)
class ExtractionResult:
    """사용자 확인 화면에 전달할 OCR 초안."""

    request_id: str
    ocr_type: str
    measured_at: str | None
    hospital_name: str | None
    document_type: str
    summary: CheckupSummary
    items: tuple[ParsedCheckupItem, ...]
    parser_mode: str = "unknown"
    warnings: tuple[str, ...] = field(default_factory=tuple)
    findings: tuple[Finding, ...] = ()
    overall_opinions: tuple[Finding, ...] = ()
    review_required: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """내부 진단 메타데이터를 제외한 사용자 검토용 응답을 만든다."""

        return {
            "request_id": self.request_id,
            "ocr_type": self.ocr_type,
            "record": {
                "measured_at": self.measured_at,
                "hospital_name": self.hospital_name,
                "document_type": self.document_type,
                "summary_data": self.summary.to_dict(),
            },
            "results": [
                {
                    "raw_name": item.raw_name,
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "value_numeric": _numeric_value(item.value),
                    "value_text": (
                        None if _numeric_value(item.value) is not None else item.value
                    ),
                    "raw_unit": item.raw_unit,
                    "normalized_unit": item.unit,
                    "status": item.printed_status,
                    "source_page": item.source_page,
                    "detail_data": item.detail_data,
                }
                for item in self.items
            ],
        }


def _numeric_value(value: str) -> int | float | None:
    """단일 숫자인 결과만 숫자형으로 변환하고 비교식·소견은 원문으로 둔다."""

    normalized = value.strip().replace(",", "")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", normalized):
        return None
    if "." not in normalized:
        return int(normalized)
    return float(normalized)


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
        """내부 진단 메타데이터를 제외한 사용자 검토용 응답을 만든다."""

        return {
            "request_id": self.request_id,
            "ocr_type": self.ocr_type,
            "prescribed_at": self.prescribed_at,
            "dispensed_at": self.dispensed_at,
            "medical_institution_name": self.medical_institution_name,
            "pharmacy_name": self.pharmacy_name,
            "medications": [
                {
                    "medicine_name": medication.medicine_name,
                    "strength": medication.strength,
                    "dose_per_intake": medication.dose_per_intake,
                    "dose_unit": medication.dose_unit,
                    "frequency_per_day": medication.frequency_per_day,
                    "duration_days": medication.duration_days,
                    "timing_labels": list(medication.timing_labels),
                    "meal_relation": medication.meal_relation,
                    "administration_note": medication.administration_note,
                }
                for medication in self.medications
            ],
        }
