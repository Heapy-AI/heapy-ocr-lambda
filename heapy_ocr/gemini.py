"""Gemini 구조화 출력 기반 건강검진 텍스트 파서.

작성자: 김진우
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from heapy_ocr.exceptions import ExternalServiceError
from heapy_ocr.models import RawCheckupItem
from heapy_ocr.rule_parser import CheckupExtraction

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "measured_at": {"type": ["string", "null"]},
        "hospital_name": {"type": ["string", "null"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_name": {"type": "string"},
                    "raw_value": {"type": "string"},
                    "raw_unit": {"type": ["string", "null"]},
                    "printed_status": {"type": ["string", "null"]},
                },
                "required": [
                    "raw_name",
                    "raw_value",
                    "raw_unit",
                    "printed_status",
                ],
            },
        },
    },
    "required": ["measured_at", "hospital_name", "items"],
}


class GeminiCheckupParser:
    """OCR 텍스트를 건강검진 항목 JSON으로 변환한다."""

    def __init__(self, api_key: str, model: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def parse(self, lines: tuple[str, ...]) -> CheckupExtraction:
        if not self.api_key:
            raise ExternalServiceError("GEMINI_API_KEY가 설정되지 않았습니다.")

        safe_lines = tuple(_redact_identifier(line) for line in lines)
        prompt = (
            "다음은 여러 병원의 건강검진 결과지를 OCR한 줄 목록입니다. 문서에 실제로 "
            "적힌 검진일, 검진기관, 검사 항목명, 결과값, 단위와 인쇄된 판정만 추출하세요. "
            "참고치·정상범위·기준치 숫자는 결과값으로 추출하지 마세요. '비해당', '미실시'인 "
            "항목과 실제 결과가 없는 항목은 제외하세요. 수치를 재판정하거나 누락된 값을 "
            "추측하지 말고, 결과가 명확한 항목만 items에 포함하세요. 같은 검사는 한 번만 "
            "포함하세요. 이 페이지 묶음에 실제 검사 결과가 없으면 items는 빈 배열로 "
            "반환하세요.\n\n"
            + json.dumps(safe_lines, ensure_ascii=False)
        )
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent",
            data=json.dumps(_request_payload(prompt), ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ExternalServiceError(_http_error_message(exc)) from exc
        except urllib.error.URLError as exc:
            raise ExternalServiceError(
                f"Gemini 연결에 실패했습니다 ({type(exc.reason).__name__})."
            ) from exc
        except TimeoutError as exc:
            raise ExternalServiceError("Gemini 응답 시간이 초과되었습니다.") from exc
        except json.JSONDecodeError as exc:
            raise ExternalServiceError("Gemini 응답이 올바른 JSON이 아닙니다.") from exc

        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ExternalServiceError("Gemini 파싱 결과 형식이 올바르지 않습니다.") from exc
        return self._validate(parsed)

    @staticmethod
    def _validate(payload: Any) -> CheckupExtraction:
        if not isinstance(payload, dict):
            raise ExternalServiceError("Gemini 파싱 결과가 객체가 아닙니다.")

        measured_at = _optional_text(payload.get("measured_at"))
        if measured_at:
            try:
                date.fromisoformat(measured_at)
            except ValueError:
                measured_at = None

        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ExternalServiceError("Gemini 검사 항목 형식이 올바르지 않습니다.")
        items = tuple(
            item
            for raw_item in raw_items
            if isinstance(raw_item, dict)
            and (item := _raw_item(raw_item)) is not None
        )
        return CheckupExtraction(
            measured_at=measured_at,
            hospital_name=_optional_text(payload.get("hospital_name")),
            items=items,
            parser_mode="gemini",
        )


def _request_payload(prompt: str) -> dict[str, Any]:
    return {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "당신은 건강검진 OCR 구조화 도구입니다. 의료 판단을 하지 않고 "
                        "입력 텍스트에 존재하는 정보만 JSON으로 반환합니다."
                    )
                }
            ]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": _RESPONSE_SCHEMA,
        },
    }


def _redact_identifier(value: str) -> str:
    value = re.sub(r"\b\d{6}\s*-\s*[1-4]\d{6}\b", "[주민등록번호 제거]", value)
    value = re.sub(r"\b\d{6}\s*-\s*[1-4*][0-9*]{5,6}\b", "[주민등록번호 제거]", value)
    return re.sub(
        r"(수검자\s*성명\s*)[^\s]+",
        r"\1[성명 제거]",
        value,
    )


def _raw_item(payload: dict[str, Any]) -> RawCheckupItem | None:
    raw_name = _optional_text(payload.get("raw_name"))
    raw_value = _optional_text(payload.get("raw_value"))
    if not raw_name or not raw_value or raw_value in {"비해당", "미실시", "미검"}:
        return None
    return RawCheckupItem(
        raw_name=raw_name,
        raw_value=raw_value,
        raw_unit=_optional_text(payload.get("raw_unit")),
        printed_status=_optional_text(payload.get("printed_status")),
    )


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    if exc.code == 429:
        return "Gemini 할당량을 초과해 규칙 파서로 전환합니다."
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        message = str(payload.get("error", {}).get("message") or f"HTTP {exc.code}")
    except (AttributeError, json.JSONDecodeError):
        message = f"HTTP {exc.code}"
    return f"Gemini 파싱에 실패했습니다: {message}"
