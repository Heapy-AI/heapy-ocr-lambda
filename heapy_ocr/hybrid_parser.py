"""Gemini 우선·규칙 기반 fallback 건강검진 파서.

작성자: 김진우
"""

from __future__ import annotations

from dataclasses import replace

from heapy_ocr.exceptions import ExternalServiceError, OcrError
from heapy_ocr.gemini import GeminiCheckupParser
from heapy_ocr.rule_parser import CheckupExtraction, RuleBasedCheckupParser


class HybridCheckupParser:
    """Gemini 실패 시 동일 OCR 원문을 규칙 파서로 처리한다."""

    def __init__(
        self,
        primary: GeminiCheckupParser,
        fallback: RuleBasedCheckupParser,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    def parse(self, lines: tuple[str, ...]) -> CheckupExtraction:
        try:
            return self.primary.parse(lines)
        except ExternalServiceError as exc:
            try:
                fallback = self.fallback.parse(lines)
            except OcrError:
                fallback = CheckupExtraction(
                    measured_at=None,
                    hospital_name=None,
                    items=(),
                )
            return replace(
                fallback,
                parser_mode="rule_fallback",
                parser_warnings=(
                    f"Gemini를 사용할 수 없어 규칙 파서를 적용했습니다: {exc.message}",
                ),
            )
