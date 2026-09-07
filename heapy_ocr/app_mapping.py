"""공개 API 검토값으로의 손실을 명시하는 매핑. 작성자: 김진우."""

import math
import re

from heapy_ocr.models import ExtractionResult, MedicationExtractionResult, _numeric_value


def safe_numeric(value: str) -> int | float | None:
    """모호한 소수 쉼표·비교식과 비유한 값을 숫자로 단정하지 않는다."""
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", value.strip()):
        return None
    try:
        number = _numeric_value(value)
        return number if math.isfinite(number) else None
    except (ValueError, OverflowError):
        return None


def dosage(item) -> str | None:
    """인식된 구성요소만 표시 문자열로 조합한다."""
    parts = []
    if item.dose_per_intake:
        parts.append(f"1회 {item.dose_per_intake}{item.dose_unit or ''}")
    if item.frequency_per_day:
        parts.append(f"1일 {item.frequency_per_day}회")
    if item.duration_days:
        parts.append(f"{item.duration_days}일")
    parts.extend(item.timing_labels)
    parts.extend(value for value in (item.meal_relation, item.administration_note) if value)
    return ", ".join(parts) or None


def map_result(result: ExtractionResult | MedicationExtractionResult) -> dict:
    if isinstance(result, ExtractionResult):
        return {
            "measuredAt": result.measured_at,
            "providerName": result.hospital_name,
            "items": [
                {
                    "fieldKey": f"result-{index}",
                    "itemCode": item.item_code,
                    "itemName": item.item_name or item.raw_name,
                    "value": item.value,
                    "numericValue": safe_numeric(item.value),
                    "unit": item.raw_unit,
                    "status": item.printed_status,
                    "confidence": None,
                }
                for index, item in enumerate(result.items, 1)
            ],
        }
    return {
        "items": [
            {
                "itemOrder": index,
                "rawName": item.raw_name,
                "rawDosage": None,
                "normalizedName": item.medicine_name,
                "normalizedDosage": dosage(item),
                "confidence": None,
            }
            for index, item in enumerate(result.medications, 1)
        ]
    }
