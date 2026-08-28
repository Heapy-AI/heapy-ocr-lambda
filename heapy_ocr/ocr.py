"""OCR 공급자 공통 계약.

작성자: 김진우
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OcrDocument:
    """OCR 공급자가 반환한 문서 텍스트와 평균 신뢰도."""

    text: str
    lines: tuple[str, ...]
    average_confidence: float


class OcrAnalyzer(Protocol):
    """이미지에서 문서 텍스트를 추출하는 공급자 계약."""

    def analyze(self, image_bytes: bytes) -> OcrDocument: ...
