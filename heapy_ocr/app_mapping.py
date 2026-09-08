"""공개 API 검토값으로의 손실을 명시하는 매핑. 작성자: 김진우."""

import json
import math
import re

from heapy_ocr.exceptions import OcrError
from heapy_ocr.findings import checked_text
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


def map_classified_result(result: ExtractionResult) -> dict:
    """검증용 버전 2 매핑. 기본 Lambda 경로에서는 아직 호출하지 않는다. 작성자: 김진우."""
    mapped = map_result(result)
    reviews = [
        {"classification": "needs_review", "text": checked_text(text, 2000),
         "reason": "uncertain_classification"}
        for text in result.review_required
    ]
    items = []
    for original, item in zip(result.items, mapped["items"], strict=True):
        if item["itemCode"] == "CHEST_XRAY_PA" and not re.search(
            r"(?<![A-Za-z])PA(?![A-Za-z])", original.raw_name, re.I
        ):
            # 촬영 방향이 없는 원문을 PA 검사로 확정하지 않는다. 신규 마스터 적용은 별도다.
            item = {**item, "itemCode": None, "itemName": original.raw_name}
        if item["itemCode"] is None:
            text = f"{item['itemName']}: {item['value']}"
            if item["unit"]:
                text += f" {item['unit']}"
            if item["status"]:
                text += f" (기관 판정: {item['status']})"
            reviews.append({"classification": "needs_review",
                            "text": checked_text(text, 2000), "reason": "unmatched_item"})
        else:
            items.append({**item, "classification": "general_test"})
    findings = [f.to_public("procedure_finding") for f in result.findings]
    opinions = [f.to_public("overall_opinion") for f in result.overall_opinions]
    if any(len(values) > limit for values, limit in (
        (items, 200), (reviews, 200), (findings, 50), (opinions, 20),
    )):
        raise OcrError("검진 결과 개수 제한을 초과했습니다.")
    for finding in (*findings, *opinions):
        if len(json.dumps(finding, ensure_ascii=False).encode("utf-8")) > 65536:
            raise OcrError("검사 소견 크기 제한을 초과했습니다.")
    mapped.update({
        "schemaVersion": 2, "items": items, "findings": findings,
        "overallOpinions": opinions,
        "reviewRequired": [{**item, "fieldKey": f"review-{index}"}
                           for index, item in enumerate(reviews, 1)],
    })
    if len(json.dumps(mapped, ensure_ascii=False).encode("utf-8")) > 262144:
        raise OcrError("검진 결과 크기 제한을 초과했습니다.")
    return mapped
