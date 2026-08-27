"""Lambda Function URL 진입점.

작성자: 김진우
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

from heapy_ocr.config import Settings
from heapy_ocr.exceptions import OcrError
from heapy_ocr.gemini import GeminiCheckupParser
from heapy_ocr.models import (
    OCR_TYPE_HEALTH_CHECKUP,
    OPERATION_CONFIRM_AND_SAVE,
    OPERATION_EXTRACT,
    ParsedCheckupItem,
)
from heapy_ocr.service import HeapyOcrService
from heapy_ocr.supabase import SupabaseGateway
from heapy_ocr.textract import TextractAnalyzer

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_service: HeapyOcrService | None = None


def _build_service() -> HeapyOcrService:
    """환경변수와 AWS SDK 클라이언트로 서비스를 생성한다."""
    import boto3

    settings = Settings.from_env()
    return HeapyOcrService(
        textract=TextractAnalyzer(boto3.client("textract")),
        parser=GeminiCheckupParser(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.external_timeout_seconds,
        ),
        supabase=SupabaseGateway(
            settings.supabase_url,
            settings.supabase_publishable_key,
            settings.external_timeout_seconds,
        ),
        max_image_bytes=settings.max_image_bytes,
    )


def _get_service() -> HeapyOcrService:
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """OCR 추출 또는 확인된 건강검진 결과 저장 요청을 처리한다."""
    del context
    try:
        settings = Settings.from_env()
        headers = _normalized_headers(event.get("headers"))
        _verify_internal_secret(headers, settings.internal_secret_key)
        access_token = _bearer_token(headers.get("authorization", ""))
        payload = _parse_body(event)

        ocr_type = str(payload.get("ocr_type", "")).strip().upper()
        if ocr_type != OCR_TYPE_HEALTH_CHECKUP:
            raise OcrError("현재 HEALTH_CHECKUP OCR만 지원합니다.")

        operation = str(payload.get("operation", OPERATION_EXTRACT)).strip().upper()
        if operation == OPERATION_EXTRACT:
            result = _extract(payload, access_token, settings.max_image_bytes)
            logger.info("건강검진 OCR 추출 완료: request_id=%s", result["request_id"])
            return _response(200, {"is_success": True, "result": result})
        if operation == OPERATION_CONFIRM_AND_SAVE:
            result = _confirm_and_save(payload, access_token)
            logger.info("건강검진 OCR 저장 완료: record_id=%s", result["record_id"])
            return _response(200, {"is_success": True, "result": result})
        raise OcrError("지원하지 않는 operation입니다.")
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
    access_token: str,
    max_image_bytes: int,
) -> dict[str, Any]:
    image_base64 = payload.get("image_base64")
    if not isinstance(image_base64, str) or not image_base64.strip():
        raise OcrError("image_base64가 필요합니다.")
    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OcrError("image_base64 형식이 올바르지 않습니다.") from exc
    if len(image_bytes) > max_image_bytes:
        raise OcrError("건강검진 결과지 이미지 크기가 허용 범위를 초과했습니다.")
    if not _supported_document(image_bytes):
        raise OcrError("JPEG, PNG, PDF 또는 TIFF 파일만 지원합니다.")
    return _get_service().extract(image_bytes, access_token).to_dict()


def _confirm_and_save(
    payload: dict[str, Any],
    access_token: str,
) -> dict[str, Any]:
    if payload.get("confirmed") is not True:
        raise OcrError("사용자 확인을 완료한 결과만 저장할 수 있습니다.")
    measured_at = payload.get("measured_at")
    raw_items = payload.get("items")
    if not isinstance(measured_at, str):
        raise OcrError("measured_at이 필요합니다.")
    if not isinstance(raw_items, list):
        raise OcrError("items는 배열이어야 합니다.")
    items = tuple(_confirmed_item(item) for item in raw_items)
    record_id = _get_service().confirm_and_save(
        access_token,
        measured_at,
        items,
    )
    return {
        "record_id": record_id,
        "measured_at": measured_at,
        "saved_item_count": len(items),
    }


def _confirmed_item(payload: Any) -> ParsedCheckupItem:
    if not isinstance(payload, dict):
        raise OcrError("검사항목 형식이 올바르지 않습니다.")
    raw_name = str(payload.get("raw_name") or payload.get("item_name") or "").strip()
    item_code = str(payload.get("item_code") or "").strip().upper()
    item_name = str(payload.get("item_name") or "").strip()
    raw_value = str(payload.get("raw_value") or payload.get("value") or "").strip()
    value = str(payload.get("value") or "").strip()
    unit = _optional_text(payload.get("unit"))
    printed_status = _optional_text(
        payload.get("printed_status", payload.get("status"))
    )
    return ParsedCheckupItem(
        raw_name=raw_name,
        item_code=item_code or None,
        item_name=item_name or None,
        raw_value=raw_value,
        value=value,
        unit=unit,
        printed_status=printed_status,
        confidence=float(payload.get("confidence", 1.0)),
        needs_review=False,
    )


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


def _bearer_token(authorization: str) -> str:
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise OcrError("사용자 인증 토큰이 필요합니다.", 401)
    token = authorization[len(prefix) :].strip()
    if not token:
        raise OcrError("사용자 인증 토큰이 필요합니다.", 401)
    return token


def _supported_document(data: bytes) -> bool:
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"%PDF-")
        or data.startswith((b"II*\x00", b"MM\x00*"))
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }
