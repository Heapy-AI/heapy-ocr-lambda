"""저장 확장용 추출 경로. 운영 활성화와 분리한다. 작성자: 김진우."""

import re
from copy import deepcopy
from dataclasses import replace

from heapy_ocr.exceptions import ExternalServiceError
from heapy_ocr.findings import (
    FINDING_INSTRUCTIONS,
    checked_text,
    finding_schema,
    parse_findings,
)
from heapy_ocr.gemini import _RESPONSE_SCHEMA, GeminiCheckupParser
from heapy_ocr.general_checkup import GENERAL_INSTRUCTIONS


def _instructions() -> str:
    """기존 행·열 검증은 유지하고 과거 소견 제외 지시만 교체한다."""
    text = GENERAL_INSTRUCTIONS.replace(
        "별도 암검진, 내시경·조직진단·초음파·CT·MRI 상세 소견은 advanced 섹션으로 제외하세요. ",
        "내시경 등 상세 소견은 items에 넣지 말고 별도 소견 배열로 보내세요. ",
    ).replace("출력은 measured_at, hospital_name, items만 포함하는 JSON입니다. ", "")
    return text + FINDING_INSTRUCTIONS


def _schema() -> dict:
    schema = deepcopy(_RESPONSE_SCHEMA)
    schema["properties"].update({
        "findings": finding_schema(),
        "overall_opinions": finding_schema(overall=True),
        "review_required": {
            "type": "array",
            "items": {"type": "object", "properties": {
                "text": {"type": "string"},
                "reason": {"type": "string", "enum": ["uncertain_classification"]},
            }, "required": ["text", "reason"], "additionalProperties": False},
        },
    })
    schema["required"] += ["findings", "overall_opinions", "review_required"]
    return schema


class ClassifiedCheckupParser(GeminiCheckupParser):
    """일반 결과·검사 소견·종합소견을 각각 추출한다. 외부 요약 호출은 없다."""

    instructions = _instructions()
    response_schema = _schema()
    select_lines = staticmethod(tuple)
    preserves_findings = True

    @staticmethod
    def _validate(payload):
        if not isinstance(payload, dict):
            raise ExternalServiceError("검진 분류 응답은 객체여야 합니다.")
        findings = parse_findings(payload.get("findings"))
        opinions = parse_findings(payload.get("overall_opinions"), overall=True)
        review = payload.get("review_required")
        if not isinstance(review, list) or len(review) > 200:
            raise ExternalServiceError("확인 필요 배열 제한 오류입니다.")
        reviews = []
        for item in review:
            if (not isinstance(item, dict) or set(item) != {"text", "reason"}
                    or item["reason"] != "uncertain_classification"):
                raise ExternalServiceError("확인 필요 항목 형식 오류입니다.")
            reviews.append(checked_text(item["text"], 2000))
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ExternalServiceError("검사 항목 형식 오류입니다.")
        accepted = []
        for item in raw_items:
            if not isinstance(item, dict):
                raise ExternalServiceError("검사 항목은 객체여야 합니다.")
            name = item.get("raw_name", "")
            # 소견이 개별 검사로 잘못 분류됐어도 검사명만으로 소견을 자동 생성하지 않는다.
            if isinstance(name, str) and re.search(
                r"내시경|조직\s*(?:검사|진단)|endoscop|colonoscopy|biopsy", name, re.I
            ):
                reviews.append(checked_text(f"{name}: {item.get('raw_value', '')}", 2000))
            else:
                accepted.append(item)
        parsed = GeminiCheckupParser._validate({**payload, "items": accepted})
        return replace(parsed, findings=findings, overall_opinions=opinions,
                       review_required=tuple(reviews))
