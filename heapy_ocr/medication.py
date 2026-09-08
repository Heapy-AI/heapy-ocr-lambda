"""Gemini 구조화 출력 기반 약봉투 텍스트 파서.

작성자: 김진우
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any

from heapy_ocr.diagnostics import mark_status, observe
from heapy_ocr.exceptions import ExternalServiceError, OcrError
from heapy_ocr.gemini import _http_error_message, _image_mime_type
from heapy_ocr.models import ParsedMedication

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "prescribed_at": {"type": ["string", "null"]},
        "dispensed_at": {"type": ["string", "null"]},
        "medical_institution_name": {"type": ["string", "null"]},
        "pharmacy_name": {"type": ["string", "null"]},
        "medications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_name": {"type": "string"},
                    "medicine_name": {"type": "string"},
                    "strength": {"type": ["string", "null"]},
                    "dose_per_intake": {"type": ["string", "null"]},
                    "dose_unit": {"type": ["string", "null"]},
                    "frequency_per_day": {"type": ["integer", "null"]},
                    "duration_days": {"type": ["integer", "null"]},
                    "timing_labels": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "meal_relation": {"type": ["string", "null"]},
                    "administration_note": {"type": ["string", "null"]},
                },
                "required": [
                    "raw_name",
                    "medicine_name",
                    "strength",
                    "dose_per_intake",
                    "dose_unit",
                    "frequency_per_day",
                    "duration_days",
                    "timing_labels",
                    "meal_relation",
                    "administration_note",
                ],
            },
        },
    },
    "required": [
        "prescribed_at",
        "dispensed_at",
        "medical_institution_name",
        "pharmacy_name",
        "medications",
    ],
}


@dataclass(frozen=True)
class MedicationExtraction:
    """Gemini가 약봉투에서 추출한 구조화 정보."""

    prescribed_at: str | None
    dispensed_at: str | None
    medical_institution_name: str | None
    pharmacy_name: str | None
    medications: tuple[ParsedMedication, ...]


class GeminiMedicationParser:
    """약봉투 이미지 또는 OCR 텍스트를 복약 일정용 JSON으로 변환한다."""

    def __init__(self, api_key: str, model: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @observe("gemini_medication")
    def parse(self, lines: tuple[str, ...]) -> MedicationExtraction:
        if not self.api_key:
            raise ExternalServiceError("GEMINI_API_KEY가 설정되지 않았습니다.")

        safe_lines = tuple(_redact_patient_identifier(line) for line in lines)
        prompt = (
            "다음은 한국 약국의 약봉투 또는 복약안내문을 OCR한 줄 목록입니다. 문서에 "
            "실제로 인쇄된 처방일, 조제일, 의료기관, 약국과 약별 복용 정보를 추출하세요. "
            "약 이름에 붙은 함량은 strength로 분리하되 medicine_name에는 제품명을 유지하세요. "
            "1회 투약량, 1일 투여 횟수, 총 투약일수, 아침·점심·저녁·취침 전 등의 복용 시점, "
            "식전·식후 관계와 기타 복용 지시를 각각 분리하세요. 여러 약은 medications 배열의 "
            "별도 항목으로 반환하세요. 약봉투의 공통 복용법이 여러 약에 동일하게 적용되면 각 "
            "약에 같은 값을 넣으세요. 정확한 시계 시간이 인쇄되지 않았다면 09:00 같은 시간을 "
            "추측하지 마세요. 환자명, 전화번호, 주소와 주민등록번호는 반환하지 마세요. 읽히지 "
            "않거나 문서에 없는 값은 null 또는 빈 배열로 두고 의학적 판단을 하지 마세요.\n\n"
            + json.dumps(safe_lines, ensure_ascii=False)
        )
        body = self._request_json(prompt)
        return self._validate(body)

    @observe("gemini_medication")
    def parse_images(
        self,
        image_pages: tuple[bytes, ...],
    ) -> MedicationExtraction:
        """약봉투 이미지를 Gemini가 직접 읽어 복약 정보로 구조화한다."""

        if not self.api_key:
            raise ExternalServiceError("GEMINI_API_KEY가 설정되지 않았습니다.")
        if not image_pages:
            raise ExternalServiceError("Gemini에 전달할 약봉투 이미지가 없습니다.")

        prompt = (
            "첨부된 한국 약국의 약봉투 또는 복약안내문 이미지를 직접 읽으세요. 문서의 "
            "표, 행과 열 배치를 함께 확인하여 처방일, 조제일, 의료기관, 약국과 약별 복용 "
            "정보를 추출하세요. 약 이름에 붙은 함량은 strength로 분리하되 medicine_name에는 "
            "제품명을 유지하세요. 1회 투약량, 1일 투여 횟수, 총 투약일수, 복용 시점, 식사 "
            "관계와 기타 지시를 각각 분리하세요. 공통 복용법은 해당하는 각 약에 적용하세요. "
            "정확한 시간이 없다면 시간을 추측하지 마세요. 환자명, 전화번호, 주소와 주민등록번호는 "
            "반환하지 말고, 읽히지 않거나 없는 값은 null 또는 빈 배열로 두세요."
        )
        body = self._request_json(prompt, image_pages)
        return self._validate(body)

    def _request_json(
        self,
        prompt: str,
        image_pages: tuple[bytes, ...] = (),
    ) -> Any:
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent",
            data=json.dumps(
                _request_payload(prompt, image_pages),
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                mark_status(response)
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ExternalServiceError(_http_error_message(exc)) from exc
        except urllib.error.URLError as exc:
            raise ExternalServiceError(
                f"Gemini 연결에 실패했습니다 ({type(exc.reason).__name__})."
            ) from exc
        except TimeoutError as exc:
            raise ExternalServiceError("Gemini 응답 시간이 초과되었습니다.") from exc
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ExternalServiceError("Gemini 응답이 올바른 JSON이 아닙니다.") from exc

        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ExternalServiceError("Gemini 약봉투 파싱 결과 형식이 올바르지 않습니다.") from exc
        return parsed

    @staticmethod
    def _validate(payload: Any) -> MedicationExtraction:
        if not isinstance(payload, dict):
            raise ExternalServiceError("Gemini 약봉투 파싱 결과가 객체가 아닙니다.")
        raw_medications = payload.get("medications")
        if not isinstance(raw_medications, list):
            raise ExternalServiceError("Gemini 약 목록 형식이 올바르지 않습니다.")

        medications = tuple(
            medication
            for raw_medication in raw_medications
            if isinstance(raw_medication, dict)
            and (medication := _medication(raw_medication)) is not None
        )
        if not medications:
            raise OcrError("OCR 원문에서 약 이름을 찾지 못했습니다.")
        return MedicationExtraction(
            prescribed_at=_date_text(payload.get("prescribed_at")),
            dispensed_at=_date_text(payload.get("dispensed_at")),
            medical_institution_name=_optional_text(
                payload.get("medical_institution_name")
            ),
            pharmacy_name=_optional_text(payload.get("pharmacy_name")),
            medications=medications,
        )


def _request_payload(
    prompt: str,
    image_pages: tuple[bytes, ...] = (),
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"text": prompt}]
    parts.extend(
        {
            "inlineData": {
                "mimeType": _image_mime_type(image_bytes),
                "data": base64.b64encode(image_bytes).decode("ascii"),
            }
        }
        for image_bytes in image_pages
    )
    return {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "당신은 약봉투 OCR 구조화 도구입니다. 의료 판단이나 복용법 추측 없이 "
                        "입력 텍스트에 존재하는 정보만 JSON으로 반환합니다."
                    )
                }
            ]
        },
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": _RESPONSE_SCHEMA,
        },
    }


def _medication(payload: dict[str, Any]) -> ParsedMedication | None:
    raw_name = _optional_text(payload.get("raw_name"))
    medicine_name = _optional_text(payload.get("medicine_name"))
    if not raw_name or not medicine_name:
        return None
    return ParsedMedication(
        raw_name=raw_name,
        medicine_name=medicine_name,
        strength=_optional_text(payload.get("strength")),
        dose_per_intake=_optional_text(payload.get("dose_per_intake")),
        dose_unit=_optional_text(payload.get("dose_unit")),
        frequency_per_day=_positive_integer(payload.get("frequency_per_day")),
        duration_days=_positive_integer(payload.get("duration_days")),
        timing_labels=_text_list(payload.get("timing_labels")),
        meal_relation=_optional_text(payload.get("meal_relation")),
        administration_note=_optional_text(payload.get("administration_note")),
    )


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _text_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if (text := _optional_text(item)) is not None)


def _date_text(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _redact_patient_identifier(value: str) -> str:
    """Gemini 전송 전에 약봉투의 대표적인 개인식별정보를 가린다."""

    value = re.sub(r"\b\d{6}\s*-\s*[1-4*][0-9*]{5,6}\b", "[주민등록번호 제거]", value)
    value = re.sub(
        r"((?:환자명|환자|성명|이름)\s*[:：]?\s*)[^\s,]+",
        r"\1[성명 제거]",
        value,
    )
    value = re.sub(
        r"\b(?:01[016789]|0\d{1,2})[-.\s]?\d{3,4}[-.\s]?\d{4}\b",
        "[전화번호 제거]",
        value,
    )
    return value
