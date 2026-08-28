"""건강검진 OCR 애플리케이션 서비스.

작성자: 김진우
"""

from __future__ import annotations

from uuid import uuid4

from heapy_ocr.catalog import MASTER_CHECKUP_ITEMS
from heapy_ocr.exceptions import OcrError
from heapy_ocr.hybrid_parser import HybridCheckupParser
from heapy_ocr.matcher import CheckupItemMatcher
from heapy_ocr.models import ExtractionResult, ParsedCheckupItem
from heapy_ocr.ocr import OcrAnalyzer, OcrDocument
from heapy_ocr.rule_parser import CheckupExtraction


class HeapyOcrService:
    """건강검진 OCR 추출과 내부 마스터 매칭 흐름을 조정한다."""

    MAX_PAGE_COUNT = 20

    def __init__(
        self,
        ocr_analyzer: OcrAnalyzer,
        parser: HybridCheckupParser,
        max_image_bytes: int,
        parser_chunk_page_count: int = 3,
    ) -> None:
        if not 1 <= parser_chunk_page_count <= 5:
            raise ValueError("파서 페이지 묶음 크기는 1~5여야 합니다.")
        self.ocr_analyzer = ocr_analyzer
        self.parser = parser
        self.max_image_bytes = max_image_bytes
        self.parser_chunk_page_count = parser_chunk_page_count

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

        documents = tuple(self.ocr_analyzer.analyze(page) for page in image_pages)
        return self.extract_documents(documents)

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
        ocr_confidence = round(
            sum(document.average_confidence for document in documents) / len(documents),
            4,
        )
        matcher = CheckupItemMatcher(MASTER_CHECKUP_ITEMS)
        matched_items = tuple(
            matcher.match(raw_item, ocr_confidence)
            for raw_item in extraction.items
        )
        items = _deduplicate_items(matched_items)

        warnings: list[str] = []
        warnings.extend(extraction.parser_warnings)
        if extraction.measured_at is None:
            warnings.append("검진일을 인식하지 못했습니다. 직접 입력해 주세요.")
        return ExtractionResult(
            request_id=str(uuid4()),
            ocr_type="HEALTH_CHECKUP",
            measured_at=extraction.measured_at,
            hospital_name=extraction.hospital_name,
            items=items,
            parser_mode=extraction.parser_mode,
            warnings=tuple(warnings),
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
                )
            )

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
        )


def _deduplicate_items(
    items: tuple[ParsedCheckupItem, ...],
) -> tuple[ParsedCheckupItem, ...]:
    """동일 검사코드가 여러 번 인식되면 가장 신뢰도 높은 결과만 남긴다."""

    unique: dict[str, ParsedCheckupItem] = {}
    unmatched: list[ParsedCheckupItem] = []
    for item in items:
        if item.item_code is None:
            unmatched.append(item)
            continue
        current = unique.get(item.item_code)
        if current is None or item.confidence > current.confidence:
            unique[item.item_code] = item
    return tuple(unique.values()) + tuple(unmatched)
