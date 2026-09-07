"""Lambda Function URL 진입점.

작성자: 김진우
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

from heapy_ocr.catalog import MASTER_CHECKUP_ITEMS
from heapy_ocr.config import Settings
from heapy_ocr.exceptions import OcrError
from heapy_ocr.gemini import GeminiCheckupParser
from heapy_ocr.google_vision import GoogleVisionAnalyzer
from heapy_ocr.medication import GeminiMedicationParser
from heapy_ocr.medication_service import MedicationOcrService
from heapy_ocr.models import (
    OCR_TYPE_HEALTH_CHECKUP,
    OCR_TYPE_MEDICATION,
    OPERATION_EXTRACT,
    OPERATION_OCR_PAGE,
    OPERATION_PARSE,
)
from heapy_ocr.ocr import OcrDocument
from heapy_ocr.rule_parser import RuleBasedCheckupParser
from heapy_ocr.service import HeapyOcrService

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_service: HeapyOcrService | None = None
_medication_service: MedicationOcrService | None = None


def _build_service() -> HeapyOcrService:
    """환경변수와 외부 서비스 어댑터로 OCR 서비스를 생성한다."""
    settings = Settings.from_env()
    return HeapyOcrService(
        ocr_analyzer=GoogleVisionAnalyzer(
            settings.google_vision_api_key,
            settings.external_timeout_seconds,
        ),
        parser=GeminiCheckupParser(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.gemini_timeout_seconds,
        ),
        max_image_bytes=settings.max_image_bytes,
        parser_chunk_page_count=settings.gemini_pages_per_request,
        fallback_parser=(
            RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS)
            if settings.google_vision_api_key
            else None
        ),
    )


def _get_service() -> HeapyOcrService:
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def _build_medication_service() -> MedicationOcrService:
    """환경변수와 외부 서비스 어댑터로 약봉투 OCR 서비스를 생성한다."""

    settings = Settings.from_env()
    return MedicationOcrService(
        ocr_analyzer=GoogleVisionAnalyzer(
            settings.google_vision_api_key,
            settings.external_timeout_seconds,
        ),
        parser=GeminiMedicationParser(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.gemini_timeout_seconds,
        ),
        max_image_bytes=settings.max_image_bytes,
    )


def _get_medication_service() -> MedicationOcrService:
    global _medication_service
    if _medication_service is None:
        _medication_service = _build_medication_service()
    return _medication_service


def _service_for_type(
    ocr_type: str,
) -> HeapyOcrService | MedicationOcrService:
    if ocr_type == OCR_TYPE_HEALTH_CHECKUP:
        return _get_service()
    if ocr_type == OCR_TYPE_MEDICATION:
        return _get_medication_service()
    raise OcrError("HEALTH_CHECKUP 또는 MEDICATION OCR만 지원합니다.")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """건강검진 또는 약봉투 OCR 추출 요청을 처리한다."""
    del context
    try:
        settings = Settings.from_env()
        headers = _normalized_headers(event.get("headers"))
        _verify_internal_secret(headers, settings.internal_secret_key)
        payload = _parse_body(event)

        ocr_type = str(payload.get("ocr_type", "")).strip().upper()
        service = _service_for_type(ocr_type)

        operation = str(payload.get("operation", OPERATION_EXTRACT)).strip().upper()
        if operation == OPERATION_EXTRACT:
            result = _extract(payload, settings.max_image_bytes, service)
            logger.info("OCR 추출 완료: type=%s request_id=%s", ocr_type, result["request_id"])
            return _response(200, {"is_success": True, "result": result})
        if operation == OPERATION_OCR_PAGE:
            result = _ocr_page(payload, settings.max_image_bytes, service)
            return _response(200, {"is_success": True, "result": result})
        if operation == OPERATION_PARSE:
            max_page_count = getattr(
                service,
                "MAX_PAGE_COUNT",
                HeapyOcrService.MAX_PAGE_COUNT,
            )
            result = service.extract_documents(
                _decode_ocr_documents(payload, max_page_count)
            ).to_dict()
            logger.info("OCR 파싱 완료: type=%s request_id=%s", ocr_type, result["request_id"])
            return _response(200, {"is_success": True, "result": result})
        raise OcrError("EXTRACT, OCR_PAGE 또는 PARSE 작업만 지원합니다.")
    except OcrError as exc:
        logger.warning("OCR 요청 처리 실패: %s", exc.message)
        return _response(
            exc.status_code,
            {"is_success": False, "result": None, "message": exc.message},
        )
    except Exception:
        logger.exception("예상하지 못한 OCR 처리 오류")
        return _response(
            500,
            {
                "is_success": False,
                "result": None,
                "message": "OCR 처리 중 오류가 발생했습니다.",
            },
        )


def _extract(
    payload: dict[str, Any],
    max_image_bytes: int,
    service: HeapyOcrService | MedicationOcrService,
) -> dict[str, Any]:
    page_images = payload.get("page_images_base64")
    if page_images is not None:
        if not isinstance(page_images, list) or not page_images:
            raise OcrError("page_images_base64는 한 개 이상의 이미지 배열이어야 합니다.")
        max_page_count = getattr(
            service,
            "MAX_PAGE_COUNT",
            HeapyOcrService.MAX_PAGE_COUNT,
        )
        if len(page_images) > max_page_count:
            raise OcrError(
                f"이미지는 최대 {max_page_count}장까지 지원합니다."
            )
        image_pages = tuple(
            _decode_image(image_base64, max_image_bytes)
            for image_base64 in page_images
        )
        return service.extract_pages(image_pages).to_dict()

    image_bytes = _decode_image(payload.get("image_base64"), max_image_bytes)
    return service.extract(image_bytes).to_dict()


def _ocr_page(
    payload: dict[str, Any],
    max_image_bytes: int,
    service: HeapyOcrService | MedicationOcrService,
) -> dict[str, Any]:
    """한 페이지 이미지만 OCR하여 Lambda 요청 크기를 일정하게 유지한다."""

    image_bytes = _decode_image(payload.get("image_base64"), max_image_bytes)
    document = service.ocr_analyzer.analyze(image_bytes)
    return {
        "text": document.text,
        "lines": list(document.lines),
        "average_confidence": document.average_confidence,
    }


def _decode_ocr_documents(
    payload: dict[str, Any],
    max_page_count: int = HeapyOcrService.MAX_PAGE_COUNT,
) -> tuple[OcrDocument, ...]:
    values = payload.get("ocr_pages")
    if not isinstance(values, list) or not values:
        raise OcrError("ocr_pages는 한 개 이상의 OCR 페이지 배열이어야 합니다.")
    if len(values) > max_page_count:
        raise OcrError(
            f"OCR 이미지는 최대 {max_page_count}장까지 지원합니다."
        )

    documents: list[OcrDocument] = []
    total_text_length = 0
    for value in values:
        if not isinstance(value, dict):
            raise OcrError("ocr_pages의 각 항목은 JSON 객체여야 합니다.")
        text = value.get("text")
        lines = value.get("lines")
        confidence = value.get("average_confidence")
        if not isinstance(text, str) or not isinstance(lines, list):
            raise OcrError("OCR 페이지의 text와 lines 형식이 올바르지 않습니다.")
        if not all(isinstance(line, str) for line in lines):
            raise OcrError("OCR 페이지의 lines에는 문자열만 포함할 수 있습니다.")
        if not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
            raise OcrError("OCR 페이지의 average_confidence는 0~1이어야 합니다.")
        total_text_length += len(text) + sum(len(line) for line in lines)
        if total_text_length > 1_000_000:
            raise OcrError("OCR 텍스트 전체 크기가 허용 범위를 초과했습니다.")
        documents.append(
            OcrDocument(
                text=text,
                lines=tuple(lines),
                average_confidence=float(confidence),
            )
        )
    return tuple(documents)


def _decode_image(image_base64: Any, max_image_bytes: int) -> bytes:
    if not isinstance(image_base64, str) or not image_base64.strip():
        raise OcrError("image_base64가 필요합니다.")
    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OcrError("image_base64 형식이 올바르지 않습니다.") from exc
    if len(image_bytes) > max_image_bytes:
        raise OcrError("건강검진 결과지 이미지 크기가 허용 범위를 초과했습니다.")
    if not _supported_document(image_bytes):
        raise OcrError("JPEG 또는 PNG 파일만 지원합니다.")
    return image_bytes


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body", "{}")
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(str(body), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
            raise OcrError("HTTP 요청 본문을 디코딩할 수 없습니다.") from exc
    if isinstance(body, dict):
        return body
    try:
        payload = json.loads(str(body))
    except json.JSONDecodeError as exc:
        raise OcrError("요청 본문이 올바른 JSON이 아닙니다.") from exc
    if not isinstance(payload, dict):
        raise OcrError("요청 본문은 JSON 객체여야 합니다.")
    return payload


def _normalized_headers(headers: Any) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    return {str(key).casefold(): str(value) for key, value in headers.items()}


def _verify_internal_secret(headers: dict[str, str], expected: str) -> None:
    if not expected:
        raise OcrError("INTERNAL_SECRET_KEY가 설정되지 않았습니다.", 503)
    if headers.get("x-internal-secret-key", "") != expected:
        raise OcrError("내부 서비스 인증에 실패했습니다.", 401)


def _supported_document(data: bytes) -> bool:
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
    )


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }
