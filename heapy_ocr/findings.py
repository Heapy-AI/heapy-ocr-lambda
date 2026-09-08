"""검사 단위 기관 소견의 내부 모델과 검증. 작성자: 김진우."""

from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from heapy_ocr.exceptions import ExternalServiceError

EXAM_TYPES = (
    "upper_gi_endoscopy", "colonoscopy", "biopsy", "ultrasound", "ct", "mri",
    "other_procedure",
)


@dataclass(frozen=True)
class Finding:
    """원문으로 구분된 검사 한 건. ID는 파싱 때 발급하고 재조회 때 유지한다."""

    exam_name: str
    text: str
    exam_type: str | None = None
    body_site: str | None = None
    method: str | None = None
    performed_at: str | None = None
    finding_id: str = field(default_factory=lambda: str(uuid4()))

    def to_public(self, classification: str) -> dict:
        return {
            "schemaVersion": 1, "findingId": self.finding_id,
            "classification": classification, "examType": self.exam_type,
            "examName": self.exam_name, "text": self.text,
            "bodySite": self.body_site, "method": self.method,
            "performedAt": self.performed_at, "summary": None,
        }


def checked_text(value, limit: int, nullable: bool = False) -> str | None:
    """백엔드 UTF-16 제한을 적용하며 초과 원문을 잘라 저장하지 않는다."""
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ExternalServiceError("소견 텍스트 형식이 올바르지 않습니다.")
    value = value.strip()
    if len(value.encode("utf-16-le")) // 2 > limit:
        raise ExternalServiceError("소견 텍스트 제한을 초과했습니다.")
    return value


def parse_findings(value, *, overall: bool = False) -> tuple[Finding, ...]:
    """모델이 검사 단위로 묶은 문장만 보존한다. 종류만으로 서로 합치지 않는다."""
    if not isinstance(value, list) or len(value) > (20 if overall else 50):
        raise ExternalServiceError("소견 배열 형식 또는 개수 제한 오류입니다.")
    output = []
    allowed = {"exam_name", "text", "exam_type", "body_site", "method", "performed_at"}
    for raw in value:
        if not isinstance(raw, dict) or raw.keys() - allowed:
            raise ExternalServiceError("소견에 허용되지 않은 필드가 있습니다.")
        exam_type = raw.get("exam_type")
        if (overall and exam_type is not None) or (not overall and exam_type not in EXAM_TYPES):
            raise ExternalServiceError("소견 검사 종류가 올바르지 않습니다.")
        context = [checked_text(raw.get(key), 200, True)
                   for key in ("body_site", "method")]
        performed_at = raw.get("performed_at")
        if performed_at is not None:
            try:
                if date.fromisoformat(performed_at).isoformat() != performed_at:
                    raise ValueError
            except (TypeError, ValueError):
                raise ExternalServiceError("소견 검사 날짜 형식 오류입니다.") from None
        if overall and any((*context, performed_at)):
            raise ExternalServiceError("종합소견에 개별 검사 맥락을 넣을 수 없습니다.")
        output.append(Finding(
            exam_name=checked_text(raw.get("exam_name"), 200),
            text=checked_text(raw.get("text"), 12000), exam_type=exam_type,
            body_site=context[0], method=context[1], performed_at=performed_at,
        ))
    return tuple(output)


def finding_schema(overall: bool = False) -> dict:
    properties = {
        "exam_name": {"type": "string"}, "text": {"type": "string"},
        "exam_type": ({"type": ["string", "null"]} if overall else
                      {"type": "string", "enum": list(EXAM_TYPES)}),
        **{key: {"type": ["string", "null"]}
           for key in ("body_site", "method", "performed_at")},
    }
    # 제공자 스키마 복잡도 제한을 피하고 개수·종합소견 null 제약은 서버에서 검증한다.
    return {"type": "array",
            "items": {"type": "object", "properties": properties,
                      "required": list(properties), "additionalProperties": False}}


FINDING_INSTRUCTIONS = (
    "내시경·조직검사·초음파·CT·MRI 등의 기관 소견은 findings에 검사 단위로 보존하세요. "
    "마스터 연결 여부나 수치 유무로 검사 종류를 결정하지 마세요. "
    "위내시경이 있다는 이유만으로 국가 위암검진으로 추정하지 마세요. "
    "한 페이지에 서로 다른 검진이 섞여도 실제 검사명과 영역별 원문을 구분하세요. "
    "각 소견은 exam_type, exam_name, text, body_site, method, performed_at를 포함합니다. "
    "exam_type은 upper_gi_endoscopy/colonoscopy/biopsy/ultrasound/ct/mri/other_procedure입니다. "
    "other_procedure도 원문에서 실제 검사 종류가 확인된 경우만 사용하세요. "
    "검사 하나의 여러 문장은 text에 줄바꿈으로 묶고, 부위·시점·검체가 다른 검사를 합치지 마세요. "
    "검체 구분은 원문 text 안에 보존하고 임의 필드를 추가하지 마세요. "
    "부위·방법·날짜는 원문에 없으면 null이며 검사 종류로 추론하지 마세요. "
    "회차의 기관 종합소견·권고는 overall_opinions에 블록 단위로 보존하세요. "
    "특정 검사 결과통보서의 권고사항은 해당 findings.text에 관찰 소견과 함께 보존하세요. "
    "위암 검진 결과통보서의 위내시경 권고를 회차 전체 overall_opinions로 옮기지 마세요. "
    "검사 결과의 기관 판정도 findings.text에 원문대로 포함하고 새 판정 필드를 만들지 마세요. "
    "종합소견은 exam_type, body_site, method, performed_at 모두 null입니다. "
    "요약·새 진단·환자 식별정보를 만들거나 반환하지 마세요. "
    "정성 청력과 흉부 X선 결과, 이름이 확인되는 설문 기반 평가 결과는 items에 유지하세요. "
    "독립 문진 응답·안내문·참고치·목표값을 검사나 소견으로 바꾸지 마세요. "
    "종류가 불명확한 실제 결과 후보는 review_required의 text와 "
    "reason=uncertain_classification으로 보존하세요. 단순 안내 문구는 여기에 넣지 마세요. "
    "출력은 measured_at, hospital_name, items, findings, overall_opinions, review_required입니다. "
)
