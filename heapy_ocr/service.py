"""건강검진 OCR 애플리케이션 서비스.

작성자: 김진우
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from heapy_ocr.catalog import MASTER_CHECKUP_ITEMS
from heapy_ocr.exceptions import ExternalServiceError, OcrError
from heapy_ocr.gemini import GeminiCheckupParser
from heapy_ocr.matcher import CheckupItemMatcher
from heapy_ocr.models import CheckupSummary, ExtractionResult, ParsedCheckupItem
from heapy_ocr.ocr import OcrAnalyzer, OcrDocument
from heapy_ocr.rule_parser import CheckupExtraction, RuleBasedCheckupParser

logger = logging.getLogger(__name__)


class HeapyOcrService:
    """건강검진 OCR 추출과 내부 마스터 매칭 흐름을 조정한다."""

    MAX_PAGE_COUNT = 20

    def __init__(
        self,
        ocr_analyzer: OcrAnalyzer,
        parser: GeminiCheckupParser,
        max_image_bytes: int,
        parser_chunk_page_count: int = 3,
        fallback_parser: RuleBasedCheckupParser | None = None,
    ) -> None:
        if not 1 <= parser_chunk_page_count <= 5:
            raise ValueError("파서 페이지 묶음 크기는 1~5여야 합니다.")
        self.ocr_analyzer = ocr_analyzer
        self.parser = parser
        self.max_image_bytes = max_image_bytes
        self.parser_chunk_page_count = parser_chunk_page_count
        self.fallback_parser = fallback_parser

    def extract(self, image_bytes: bytes) -> ExtractionResult:
        return self.extract_pages((image_bytes,))

    def extract_pages(
        self,
        image_pages: tuple[bytes, ...],
    ) -> ExtractionResult:
        """한 장의 이미지 또는 PDF에서 변환된 여러 페이지를 함께 추출한다."""

        if not image_pages:
            raise OcrError("건강검진 결과지 이미지가 필요합니다.")
        if len(image_pages) > self.MAX_PAGE_COUNT:
            raise OcrError(f"PDF는 최대 {self.MAX_PAGE_COUNT}페이지까지 지원합니다.")
        for image_bytes in image_pages:
            if not image_bytes:
                raise OcrError("빈 PDF 페이지가 포함되어 있습니다.")
            if len(image_bytes) > self.max_image_bytes:
                raise OcrError("건강검진 결과지 이미지 크기가 허용 범위를 초과했습니다.")

        extraction = self._parse_image_chunks(image_pages)
        return self._build_result(extraction)

    def extract_documents(
        self,
        documents: tuple[OcrDocument, ...],
    ) -> ExtractionResult:
        """이미 OCR이 끝난 여러 페이지를 하나의 검진 결과로 구조화한다."""

        if not documents:
            raise OcrError("구조화할 OCR 페이지가 없습니다.")
        if len(documents) > self.MAX_PAGE_COUNT:
            raise OcrError(f"PDF는 최대 {self.MAX_PAGE_COUNT}페이지까지 지원합니다.")
        extraction = self._parse_document_chunks(documents)
        return self._build_result(extraction)

    def _build_result(self, extraction: CheckupExtraction) -> ExtractionResult:
        """구조화 결과를 마스터 항목에 연결해 검토용 응답을 만든다."""

        matcher = CheckupItemMatcher(MASTER_CHECKUP_ITEMS)
        matched_items = tuple(
            matcher.match(raw_item, 1.0)
            for raw_item in extraction.items
        )
        items = _deduplicate_items(matched_items)

        warnings: list[str] = []
        warnings.extend(extraction.parser_warnings)
        if extraction.measured_at is None:
            warnings.append("검진일을 인식하지 못했습니다. 직접 입력해 주세요.")
        request_id = str(uuid4())
        logger.info(
            "OCR 처리 메타데이터: request_id=%s ocr_type=HEALTH_CHECKUP "
            "parser_mode=%s warning_count=%d",
            request_id,
            extraction.parser_mode,
            len(warnings),
        )
        return ExtractionResult(
            request_id=request_id,
            ocr_type="HEALTH_CHECKUP",
            measured_at=extraction.measured_at,
            hospital_name=extraction.hospital_name,
            document_type=extraction.document_type,
            summary=extraction.summary,
            items=items,
            parser_mode=extraction.parser_mode,
            warnings=tuple(warnings),
        )

    def _parse_image_chunks(
        self,
        image_pages: tuple[bytes, ...],
    ) -> CheckupExtraction:
        """페이지 이미지를 작은 묶음으로 나눠 Gemini가 직접 구조화한다."""

        extractions: list[CheckupExtraction] = []
        for start in range(0, len(image_pages), self.parser_chunk_page_count):
            chunk = image_pages[start : start + self.parser_chunk_page_count]
            try:
                parsed = self.parser.parse_images(chunk, start + 1)
            except ExternalServiceError as exc:
                parsed = self._fallback_image_chunk(chunk, start, exc)
            extractions.append(parsed)
        return self._merge_extractions(extractions)

    def _fallback_image_chunk(
        self,
        image_pages: tuple[bytes, ...],
        start: int,
        cause: ExternalServiceError,
    ) -> CheckupExtraction:
        """Gemini 장애 시에만 Vision OCR과 규칙 파서를 실행한다."""

        if self.fallback_parser is None:
            raise cause
        documents = tuple(self.ocr_analyzer.analyze(page) for page in image_pages)
        lines = tuple(
            line
            for offset, document in enumerate(documents)
            for line in (f"--- {start + offset + 1}페이지 ---", *document.lines)
        )
        try:
            fallback = self.fallback_parser.parse(lines)
        except OcrError:
            fallback = CheckupExtraction(None, None, ())
        page_end = start + len(image_pages)
        page_label = (
            f"{start + 1}페이지"
            if start + 1 == page_end
            else f"{start + 1}~{page_end}페이지"
        )
        return CheckupExtraction(
            measured_at=fallback.measured_at,
            hospital_name=fallback.hospital_name,
            items=fallback.items,
            parser_mode="rule_fallback",
            parser_warnings=(
                f"{page_label}: Gemini 직접 처리가 실패해 Vision 규칙 파서를 적용했습니다: "
                f"{cause.message}",
            ),
        )

    def _parse_document_chunks(
        self,
        documents: tuple[OcrDocument, ...],
    ) -> CheckupExtraction:
        """OCR 페이지를 작은 묶음으로 나눠 Gemini 타임아웃 범위를 제한한다."""

        extractions: list[CheckupExtraction] = []
        for start in range(0, len(documents), self.parser_chunk_page_count):
            chunk = documents[start : start + self.parser_chunk_page_count]
            lines = tuple(
                line
                for offset, document in enumerate(chunk)
                for line in (f"--- {start + offset + 1}페이지 ---", *document.lines)
            )
            parsed = self.parser.parse(lines)
            page_end = start + len(chunk)
            page_label = (
                f"{start + 1}페이지"
                if start + 1 == page_end
                else f"{start + 1}~{page_end}페이지"
            )
            extractions.append(
                CheckupExtraction(
                    measured_at=parsed.measured_at,
                    hospital_name=parsed.hospital_name,
                    items=parsed.items,
                    parser_mode=parsed.parser_mode,
                    parser_warnings=tuple(
                        f"{page_label}: {warning}"
                        for warning in parsed.parser_warnings
                    ),
                    document_type=parsed.document_type,
                    summary=parsed.summary,
                )
            )

        return self._merge_extractions(extractions)

    @staticmethod
    def _merge_extractions(
        extractions: list[CheckupExtraction],
    ) -> CheckupExtraction:
        items = tuple(
            item
            for extraction in extractions
            for item in extraction.items
        )
        if not items:
            raise OcrError("OCR 원문에서 저장 가능한 건강검진 항목을 찾지 못했습니다.")
        modes = {extraction.parser_mode for extraction in extractions}
        if modes == {"gemini"}:
            parser_mode = "gemini"
        elif modes == {"rule_fallback"}:
            parser_mode = "rule_fallback"
        else:
            parser_mode = "gemini_with_rule_fallback"
        return CheckupExtraction(
            measured_at=next(
                (
                    extraction.measured_at
                    for extraction in extractions
                    if extraction.measured_at
                ),
                None,
            ),
            hospital_name=next(
                (
                    extraction.hospital_name
                    for extraction in extractions
                    if extraction.hospital_name
                ),
                None,
            ),
            items=items,
            parser_mode=parser_mode,
            parser_warnings=tuple(
                warning
                for extraction in extractions
                for warning in extraction.parser_warnings
            ),
            document_type=_merged_document_type(extractions),
            summary=_merge_summaries(extractions),
        )


def _deduplicate_items(
    items: tuple[ParsedCheckupItem, ...],
) -> tuple[ParsedCheckupItem, ...]:
    """동일 검사코드가 여러 번 인식되면 가장 신뢰도 높은 결과만 남긴다."""

    unique: dict[str, ParsedCheckupItem] = {}
    unmatched: dict[tuple[str, str, str | None], ParsedCheckupItem] = {}
    for item in items:
        if item.item_code is None:
            key = (item.raw_name.casefold(), item.value, item.raw_unit)
            unmatched.setdefault(key, item)
            continue
        current = unique.get(item.item_code)
        item_score = (item.confidence, bool(item.detail_data))
        current_score = (
            (current.confidence, bool(current.detail_data)) if current else (-1.0, False)
        )
        if item_score > current_score:
            unique[item.item_code] = item
    return tuple(unique.values()) + tuple(unmatched.values())


def _merged_document_type(extractions: list[CheckupExtraction]) -> str:
    types = {extraction.document_type for extraction in extractions}
    if "COMPREHENSIVE" in types:
        return "COMPREHENSIVE"
    if "GENERAL" in types:
        return "GENERAL"
    return "UNKNOWN"


def _merge_summaries(extractions: list[CheckupExtraction]) -> CheckupSummary:
    summaries = [extraction.summary for extraction in extractions]
    return CheckupSummary(
        overall_status=next(
            (summary.overall_status for summary in summaries if summary.overall_status),
            None,
        ),
        suspected_diseases=_unique_texts(
            value for summary in summaries for value in summary.suspected_diseases
        ),
        diagnosed_diseases=_unique_texts(
            value for summary in summaries for value in summary.diagnosed_diseases
        ),
        lifestyle_recommendations=_unique_texts(
            value
            for summary in summaries
            for value in summary.lifestyle_recommendations
        ),
        recommendations=_unique_texts(
            value for summary in summaries for value in summary.recommendations
        ),
        risk_assessments=_unique_dicts(
            value for summary in summaries for value in summary.risk_assessments
        ),
    )


def _unique_texts(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _unique_dicts(values: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    unique: dict[str, dict[str, Any]] = {}
    for value in values:
        key = repr(sorted(value.items()))
        unique.setdefault(key, value)
    return tuple(unique.values())
