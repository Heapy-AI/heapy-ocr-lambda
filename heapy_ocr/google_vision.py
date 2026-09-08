"""Google Cloud Vision 기반 한국어 문서 OCR 어댑터.

작성자: 김진우
"""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from statistics import median
from typing import Any

from heapy_ocr.diagnostics import mark_status, observe
from heapy_ocr.exceptions import ExternalServiceError
from heapy_ocr.ocr import OcrDocument


class GoogleVisionAnalyzer:
    """Cloud Vision DOCUMENT_TEXT_DETECTION으로 한국어 문서를 분석한다."""

    def __init__(self, api_key: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @observe("vision")
    def analyze(self, image_bytes: bytes) -> OcrDocument:
        if not self.api_key:
            raise ExternalServiceError("GOOGLE_VISION_API_KEY가 설정되지 않았습니다.")
        if not image_bytes:
            raise ExternalServiceError("OCR을 실행할 이미지가 없습니다.")

        payload = {
            "requests": [
                {
                    "image": {
                        "content": base64.b64encode(image_bytes).decode("ascii"),
                    },
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                    "imageContext": {"languageHints": ["ko", "en"]},
                }
            ]
        }
        query = urllib.parse.urlencode({"key": self.api_key})
        request = urllib.request.Request(
            f"https://vision.googleapis.com/v1/images:annotate?{query}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
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
            message = _http_error_message(exc)
            raise ExternalServiceError(f"Google Vision OCR에 실패했습니다: {message}") from exc
        except urllib.error.URLError as exc:
            message = _connection_error_message(exc)
            raise ExternalServiceError(
                f"Google Vision OCR에 연결할 수 없습니다: {message}"
            ) from exc
        except TimeoutError as exc:
            raise ExternalServiceError("Google Vision OCR 응답 시간이 초과되었습니다.") from exc
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ExternalServiceError(
                "Google Vision OCR 응답이 올바른 JSON 형식이 아닙니다."
            ) from exc

        return self._parse_response(body)

    @staticmethod
    def _parse_response(payload: Any) -> OcrDocument:
        try:
            vision_response = payload["responses"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExternalServiceError("Google Vision OCR 응답 형식이 올바르지 않습니다.") from exc

        error = vision_response.get("error")
        if isinstance(error, dict):
            code = {
                4: "TIMEOUT",
                7: "AUTH_FAILED",
                16: "AUTH_FAILED",
                8: "RATE_LIMITED",
                14: "SERVER_ERROR",
            }.get(error.get("code"), "HTTP_ERROR")
            raise ExternalServiceError("Google Vision OCR 호출 실패", code, 200)

        annotation = vision_response.get("fullTextAnnotation")
        if not isinstance(annotation, dict):
            raise ExternalServiceError(
                "결과지에서 텍스트를 인식하지 못했습니다.", "EMPTY_RESULT", 200
            )
        text = str(annotation.get("text") or "").strip()
        if not text:
            raise ExternalServiceError(
                "결과지에서 텍스트를 인식하지 못했습니다.", "EMPTY_RESULT", 200
            )

        lines = _spatial_lines(annotation)
        if not lines:
            lines = tuple(line.strip() for line in text.splitlines() if line.strip())
        confidence_values = _word_confidences(annotation)
        average = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        return OcrDocument(
            text=text,
            lines=lines,
            average_confidence=round(average, 4),
        )


def _word_confidences(annotation: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for page in annotation.get("pages", []):
        for block in page.get("blocks", []):
            for paragraph in block.get("paragraphs", []):
                for word in paragraph.get("words", []):
                    confidence = word.get("confidence")
                    if isinstance(confidence, int | float):
                        values.append(float(confidence))
    return values


@dataclass(frozen=True)
class _LocatedWord:
    text: str
    left: float
    center_y: float
    height: float


def _spatial_lines(annotation: dict[str, Any]) -> tuple[str, ...]:
    """Vision 단어 좌표를 사용해 표 문서를 실제 행 순서로 재구성한다."""

    result: list[str] = []
    for page in annotation.get("pages", []):
        words = _located_words(page)
        if not words:
            continue
        tolerance = max(median(word.height for word in words) * 0.7, 0.005)
        rows: list[list[_LocatedWord]] = []
        row_centers: list[float] = []
        for word in sorted(words, key=lambda item: (item.center_y, item.left)):
            target = next(
                (
                    index
                    for index, center in enumerate(row_centers)
                    if abs(word.center_y - center) <= tolerance
                ),
                None,
            )
            if target is None:
                rows.append([word])
                row_centers.append(word.center_y)
                continue
            rows[target].append(word)
            row_centers[target] = sum(item.center_y for item in rows[target]) / len(rows[target])
        ordered_rows = sorted(zip(row_centers, rows, strict=True), key=lambda row: row[0])
        result.extend(
            " ".join(word.text for word in sorted(row, key=lambda item: item.left))
            for _, row in ordered_rows
        )
    return tuple(line for line in result if line)


def _located_words(page: dict[str, Any]) -> list[_LocatedWord]:
    result: list[_LocatedWord] = []
    for block in page.get("blocks", []):
        for paragraph in block.get("paragraphs", []):
            for word in paragraph.get("words", []):
                text = "".join(
                    str(symbol.get("text") or "") for symbol in word.get("symbols", [])
                ).strip()
                vertices = word.get("boundingBox", {}).get("vertices", [])
                if not text or not vertices:
                    continue
                xs = [float(vertex.get("x", 0)) for vertex in vertices]
                ys = [float(vertex.get("y", 0)) for vertex in vertices]
                height = max(max(ys) - min(ys), 1.0)
                result.append(
                    _LocatedWord(
                        text=text,
                        left=min(xs),
                        center_y=(min(ys) + max(ys)) / 2,
                        height=height,
                    )
                )
    return result


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    """외부 응답 본문은 오류 메시지에 포함하지 않는다."""
    return f"HTTP {exc.code}"


def _connection_error_message(exc: urllib.error.URLError) -> str:
    """API 키를 노출하지 않고 네트워크 실패 원인을 설명한다."""

    reason = exc.reason
    winerror = getattr(reason, "winerror", None)
    if winerror == 10013:
        return "운영체제가 Python의 외부 연결을 차단했습니다 (WinError 10013)."
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "SSL 인증서 검증에 실패했습니다."
    if isinstance(reason, TimeoutError):
        return "응답 시간이 초과되었습니다."
    return f"네트워크 오류가 발생했습니다 ({type(reason).__name__})."
