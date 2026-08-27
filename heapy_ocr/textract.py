"""Amazon Textract 문서 분석 어댑터.

작성자: 김진우
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from heapy_ocr.exceptions import ExternalServiceError


class TextractClientProtocol(Protocol):
    """테스트 가능한 최소 Textract 클라이언트 계약."""

    def analyze_document(
        self,
        *,
        Document: dict[str, bytes],
        FeatureTypes: list[str],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class TextractDocument:
    """Textract 응답에서 정리한 문서 텍스트."""

    lines: tuple[str, ...]
    average_confidence: float


class TextractAnalyzer:
    """건강검진표의 표·양식 구조와 전체 줄을 분석한다."""

    def __init__(self, client: TextractClientProtocol) -> None:
        self.client = client

    def analyze(self, image_bytes: bytes) -> TextractDocument:
        try:
            response = self.client.analyze_document(
                Document={"Bytes": image_bytes},
                FeatureTypes=["TABLES", "FORMS"],
            )
        except Exception as exc:
            raise ExternalServiceError("Textract 문서 분석에 실패했습니다.") from exc

        line_blocks = [
            block
            for block in response.get("Blocks", [])
            if block.get("BlockType") == "LINE" and str(block.get("Text", "")).strip()
        ]
        if not line_blocks:
            raise ExternalServiceError("결과지에서 텍스트를 인식하지 못했습니다.")

        lines = tuple(str(block["Text"]).strip() for block in line_blocks)
        confidence_values = [
            float(block.get("Confidence", 0.0))
            for block in line_blocks
            if block.get("Confidence") is not None
        ]
        average = (
            sum(confidence_values) / len(confidence_values) / 100.0
            if confidence_values
            else 0.0
        )
        return TextractDocument(lines=lines, average_confidence=round(average, 4))
