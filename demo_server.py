"""HEAPY OCR 로컬 데모 서버.

작성자: 김진우
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from heapy_ocr.config import Settings
from heapy_ocr.exceptions import OcrError
from heapy_ocr.google_vision import GoogleVisionAnalyzer
from heapy_ocr.models import OCR_TYPE_HEALTH_CHECKUP, OCR_TYPE_MEDICATION
from heapy_ocr.ocr import OcrDocument
from heapy_ocr.service import HeapyOcrService
from lambda_function import _build_medication_service, _build_service

HOST = "127.0.0.1"
PORT = 8080
MAX_REQUEST_BYTES = 30 * 1024 * 1024
ENV_FILE = Path(__file__).parent / ".env"
DEMO_HTML = Path(__file__).parent / "demo" / "index.html"
PDFJS_FILES = {
    "/vendor/pdfjs-4.10.38/pdf.min.mjs": DEMO_HTML.parent
    / "vendor"
    / "pdfjs-4.10.38"
    / "pdf.min.mjs",
    "/vendor/pdfjs-4.10.38/pdf.worker.min.mjs": DEMO_HTML.parent
    / "vendor"
    / "pdfjs-4.10.38"
    / "pdf.worker.min.mjs",
}

logger = logging.getLogger(__name__)


def _load_local_env(path: Path = ENV_FILE) -> int:
    """로컬 데모용 .env를 읽되 기존 프로세스 환경변수는 유지한다."""

    if not path.is_file():
        return 0

    loaded_count = 0
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise RuntimeError(f".env {line_number}번째 줄의 형식이 올바르지 않습니다.")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
            loaded_count += 1
    return loaded_count


class DemoRequestHandler(BaseHTTPRequestHandler):
    """정적 데모 화면과 로컬 OCR API를 제공한다."""

    server_version = "HeapyOcrDemo/1.0"

    def do_GET(self) -> None:  # noqa: N802
        pdfjs_file = PDFJS_FILES.get(self.path)
        if pdfjs_file is not None:
            self._send_file(pdfjs_file, "text/javascript; charset=utf-8")
            return
        if self.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_file(DEMO_HTML, "text/html; charset=utf-8")

    def _send_file(self, path: Path, content_type: str) -> None:
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = self._read_json()
            ocr_type = _ocr_type(payload)
            service = (
                _build_medication_service()
                if ocr_type == OCR_TYPE_MEDICATION
                else _build_service()
            )
            if self.path == "/api/vision":
                result = self._vision_result(_decode_images(payload))
            elif self.path == "/api/extract":
                result = service.extract_pages(
                    _decode_images(payload, service.MAX_PAGE_COUNT)
                ).to_dict()
            elif self.path == "/api/parse":
                result = service.extract_documents(
                    _decode_ocr_documents(payload, service.MAX_PAGE_COUNT)
                ).to_dict()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_json(HTTPStatus.OK, {"is_success": True, "result": result})
        except OcrError as exc:
            self._send_json(
                exc.status_code,
                {"is_success": False, "result": None, "message": exc.message},
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"is_success": False, "result": None, "message": str(exc)},
            )
        except Exception:
            logger.exception("로컬 OCR 데모 처리 중 오류")
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "is_success": False,
                    "result": None,
                    "message": "데모 처리 중 오류가 발생했습니다.",
                },
            )

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            raise OcrError("요청 이미지가 너무 크거나 비어 있습니다.")
        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise OcrError("요청 본문은 JSON 객체여야 합니다.")
        return payload

    @staticmethod
    def _vision_result(image_pages: tuple[bytes, ...]) -> dict[str, Any]:
        settings = Settings.from_env()
        analyzer = GoogleVisionAnalyzer(
            settings.google_vision_api_key,
            settings.external_timeout_seconds,
        )
        documents = tuple(analyzer.analyze(page) for page in image_pages)
        text = "\n\n".join(
            f"[{page_number}페이지]\n{document.text}"
            for page_number, document in enumerate(documents, start=1)
        )
        lines = tuple(line for document in documents for line in document.lines)
        average_confidence = round(
            sum(document.average_confidence for document in documents) / len(documents),
            4,
        )
        return {
            "text": text,
            "lines": lines,
            "page_count": len(documents),
            "average_confidence": average_confidence,
        }

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def _ocr_type(payload: dict[str, Any]) -> str:
    value = str(payload.get("ocr_type", OCR_TYPE_HEALTH_CHECKUP)).strip().upper()
    if value not in {OCR_TYPE_HEALTH_CHECKUP, OCR_TYPE_MEDICATION}:
        raise OcrError("HEALTH_CHECKUP 또는 MEDICATION OCR만 지원합니다.")
    return value


def _decode_images(
    payload: dict[str, Any],
    max_page_count: int = HeapyOcrService.MAX_PAGE_COUNT,
) -> tuple[bytes, ...]:
    values = payload.get("page_images_base64")
    if values is None:
        values = [payload.get("image_base64")]
    if not isinstance(values, list) or not values:
        raise OcrError("테스트할 이미지를 선택해 주세요.")
    if len(values) > max_page_count:
        raise OcrError(
            f"이미지는 최대 {max_page_count}장까지 지원합니다."
        )
    return tuple(_decode_image(value) for value in values)


def _decode_ocr_documents(
    payload: dict[str, Any],
    max_page_count: int = HeapyOcrService.MAX_PAGE_COUNT,
) -> tuple[OcrDocument, ...]:
    """브라우저가 페이지별로 얻은 OCR 결과를 공통 문서 모델로 변환한다."""

    values = payload.get("ocr_pages")
    if not isinstance(values, list) or not values:
        raise OcrError("파싱할 OCR 페이지가 없습니다.")
    if len(values) > max_page_count:
        raise OcrError(
            f"OCR 이미지는 최대 {max_page_count}장까지 지원합니다."
        )

    documents: list[OcrDocument] = []
    for value in values:
        if not isinstance(value, dict):
            raise OcrError("OCR 페이지 형식이 올바르지 않습니다.")
        text = value.get("text")
        lines = value.get("lines")
        confidence = value.get("average_confidence")
        if not isinstance(text, str) or not isinstance(lines, list):
            raise OcrError("OCR 페이지의 text와 lines가 필요합니다.")
        if not all(isinstance(line, str) for line in lines):
            raise OcrError("OCR 페이지의 lines에는 문자열만 포함할 수 있습니다.")
        if not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
            raise OcrError("OCR 신뢰도는 0~1 사이여야 합니다.")
        documents.append(
            OcrDocument(text, tuple(lines), float(confidence))
        )
    return tuple(documents)


def _decode_image(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise OcrError("테스트할 이미지를 선택해 주세요.")
    try:
        image_bytes = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OcrError("이미지 데이터 형식이 올바르지 않습니다.") from exc
    settings = Settings.from_env()
    if len(image_bytes) > settings.max_image_bytes:
        raise OcrError("이미지 크기가 허용 범위를 초과했습니다.")
    if not (
        image_bytes.startswith(b"\xff\xd8\xff")
        or image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    ):
        raise OcrError("JPEG 또는 PNG 이미지만 지원합니다.")
    return image_bytes


def main() -> None:
    """로컬 전용 데모 서버를 실행한다."""

    loaded_count = _load_local_env()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    server = ThreadingHTTPServer((HOST, PORT), DemoRequestHandler)
    if ENV_FILE.is_file():
        print(f"로컬 설정: .env에서 {loaded_count}개 항목을 읽었습니다.")
    print(f"HEAPY OCR 데모: http://{HOST}:{PORT}")
    print("종료하려면 Ctrl+C를 누르세요.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n데모 서버를 종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
