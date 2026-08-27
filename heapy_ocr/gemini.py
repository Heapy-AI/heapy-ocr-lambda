"""Gemini 구조화 출력 기반 건강검진 텍스트 파서.

작성자: 김진우
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any

from heapy_ocr.exceptions import ExternalServiceError
from heapy_ocr.models import RawCheckupItem

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "measured_at": {
            "type": ["string", "null"],
            "description": "검진일 YYYY-MM-DD. 문서에 없으면 null",
        },
        "hospital_name": {
            "type": ["string", "null"],
            "description": "검진기관명. 문서에 없으면 null",
        },
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


@dataclass(frozen=True)
class GeminiExtraction:
    """Gemini가 반환한 문서 구조."""

    measured_at: str | None
    hospital_name: str | None
    items: tuple[RawCheckupItem, ...]


class GeminiCheckupParser:
    """Textract 텍스트를 건강검진 항목 JSON으로 변환한다."""

    def __init__(self, api_key: str, model: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def parse(self, lines: tuple[str, ...]) -> GeminiExtraction:
        if not self.api_key:
            raise ExternalServiceError("GEMINI_API_KEY가 설정되지 않았습니다.")

        prompt = (
            "다음은 건강검진 결과지를 OCR한 줄 목록입니다. 문서에 실제로 적힌 "
            "검진일, 검진기관, 검사 항목명, 결과값, 단위, 인쇄된 판정만 추출하세요. "
            "참고치나 정상범위 숫자는 검사 결과값으로 추출하지 마세요. 수치를 재판정하거나 "
            "누락된 값을 추측하지 마세요. 검사 결과가 명확한 행만 items에 포함하세요.\n\n"
            + json.dumps(lines, ensure_ascii=False)
        )
        payload = {
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
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
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
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ExternalServiceError("Gemini 건강검진 파싱에 실패했습니다.") from exc

        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ExternalServiceError("Gemini 파싱 결과 형식이 올바르지 않습니다.") from exc
        return self._validate(parsed)

    @staticmethod
    def _validate(payload: Any) -> GeminiExtraction:
        if not isinstance(payload, dict):
            raise ExternalServiceError("Gemini 파싱 결과가 객체가 아닙니다.")

        measured_at = _optional_text(payload.get("measured_at"))
        if measured_at:
            try:
                date.fromisoformat(measured_at)
            except ValueError:
                measured_at = None

        hospital_name = _optional_text(payload.get("hospital_name"))
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ExternalServiceError("Gemini 검사 항목 형식이 올바르지 않습니다.")

        items: list[RawCheckupItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            raw_name = _optional_text(raw_item.get("raw_name"))
            raw_value = _optional_text(raw_item.get("raw_value"))
            if not raw_name or not raw_value:
                continue
            items.append(
                RawCheckupItem(
                    raw_name=raw_name,
                    raw_value=raw_value,
                    raw_unit=_optional_text(raw_item.get("raw_unit")),
                    printed_status=_optional_text(raw_item.get("printed_status")),
                )
            )
        if not items:
            raise ExternalServiceError("저장 가능한 건강검진 항목을 추출하지 못했습니다.")
        return GeminiExtraction(
            measured_at=measured_at,
            hospital_name=hospital_name,
            items=tuple(items),
        )


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
