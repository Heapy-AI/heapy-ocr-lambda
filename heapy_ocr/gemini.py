"""Gemini 구조화 출력 기반 건강검진 텍스트 파서.

작성자: 김진우
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from heapy_ocr.diagnostics import mark_status, observe
from heapy_ocr.exceptions import ExternalServiceError
from heapy_ocr.general_checkup import GENERAL_INSTRUCTIONS, general_lines
from heapy_ocr.models import CheckupSummary, RawCheckupItem
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
                    "source_page": {"type": ["integer", "null"]},
                },
                "required": ["raw_name", "raw_value", "raw_unit", "printed_status", "source_page"],
            },
        },
    },
    "required": ["measured_at", "hospital_name", "items"],
}


class GeminiCheckupParser:
    """건강검진 이미지 또는 OCR 텍스트를 항목 JSON으로 변환한다."""

    def __init__(self, api_key: str, model: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @observe("gemini")
    def parse(self, lines: tuple[str, ...]) -> CheckupExtraction:
        if not self.api_key:
            raise ExternalServiceError("GEMINI_API_KEY가 설정되지 않았습니다.")

        safe_lines = tuple(_redact_identifier(line) for line in general_lines(lines))
        prompt = GENERAL_INSTRUCTIONS + "\n\n" + json.dumps(safe_lines, ensure_ascii=False)
        body = self._request_json(prompt)
        return self._validate(body)

    @observe("gemini")
    def parse_images(
        self,
        image_pages: tuple[bytes, ...],
        first_page_number: int = 1,
    ) -> CheckupExtraction:
        """페이지 이미지를 Gemini가 직접 읽어 건강검진 결과로 구조화한다."""

        if not self.api_key:
            raise ExternalServiceError("GEMINI_API_KEY가 설정되지 않았습니다.")
        if not image_pages:
            raise ExternalServiceError("Gemini에 전달할 건강검진 이미지가 없습니다.")

        last_page_number = first_page_number + len(image_pages) - 1
        page_label = (
            f"{first_page_number}페이지"
            if first_page_number == last_page_number
            else f"{first_page_number}~{last_page_number}페이지"
        )
        prompt = GENERAL_INSTRUCTIONS + (
            f" 첨부 이미지 범위는 {page_label}입니다. source_page는 실제 PDF 페이지 번호입니다."
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
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
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
            raise ExternalServiceError("Gemini 파싱 결과 형식이 올바르지 않습니다.") from exc
        return parsed

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
            document_type=_document_type(payload.get("document_type")),
            summary=_summary(payload.get("summary_data")),
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
                        "당신은 건강검진 OCR 구조화 도구입니다. 의료 판단을 하지 않고 "
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


def _image_mime_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    raise ExternalServiceError("Gemini에는 JPEG 또는 PNG 이미지만 전달할 수 있습니다.")


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
        source_page=_positive_integer(payload.get("source_page")),
        detail_data=_detail_data(payload.get("detail_data")),
    )


def _summary(value: Any) -> CheckupSummary:
    if not isinstance(value, dict):
        return CheckupSummary()
    return CheckupSummary(
        overall_status=_optional_text(value.get("overall_status")),
        suspected_diseases=_text_tuple(value.get("suspected_diseases")),
        diagnosed_diseases=_text_tuple(value.get("diagnosed_diseases")),
        lifestyle_recommendations=_text_tuple(value.get("lifestyle_recommendations")),
        recommendations=_text_tuple(value.get("recommendations")),
        risk_assessments=tuple(
            {
                "name": name,
                "value": _optional_text(item.get("value")),
                "unit": _optional_text(item.get("unit")),
                "description": _optional_text(item.get("description")),
                "source_page": _positive_integer(item.get("source_page")),
            }
            for item in value.get("risk_assessments", [])
            if isinstance(item, dict)
            and (name := _optional_text(item.get("name"))) is not None
        ),
    )


def _detail_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    findings = [
        {
            "name": name,
            "site": _optional_text(item.get("site")),
            "description": _optional_text(item.get("description")),
        }
        for item in value.get("findings", [])
        if isinstance(item, dict)
        and (name := _optional_text(item.get("name"))) is not None
    ]
    detail = {
        "interpretation": _optional_text(value.get("interpretation")),
        "recommendation": _optional_text(value.get("recommendation")),
        "findings": findings,
    }
    return detail if any((detail["interpretation"], detail["recommendation"], findings)) else {}


def _text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if (text := _optional_text(item)) is not None)


def _positive_integer(value: Any) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


def _document_type(value: Any) -> str:
    document_type = _optional_text(value)
    if document_type in {"GENERAL", "COMPREHENSIVE"}:
        return document_type
    return "UNKNOWN"


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    """외부 응답 본문은 오류 메시지에 포함하지 않는다."""
    return f"HTTP {exc.code}"
