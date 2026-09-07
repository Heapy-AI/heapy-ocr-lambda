"""약봉투 OCR 애플리케이션 서비스.

작성자: 김진우
"""

from __future__ import annotations

import logging
from uuid import uuid4

from heapy_ocr.exceptions import OcrError
from heapy_ocr.medication import GeminiMedicationParser, MedicationExtraction
from heapy_ocr.models import OCR_TYPE_MEDICATION, MedicationExtractionResult
from heapy_ocr.ocr import OcrAnalyzer, OcrDocument

logger = logging.getLogger(__name__)


class MedicationOcrService:
    """약봉투 이미지 OCR과 복약 정보 구조화를 조정한다."""

    MAX_PAGE_COUNT = 5

    def __init__(
        self,
        ocr_analyzer: OcrAnalyzer,
        parser: GeminiMedicationParser,
        max_image_bytes: int,
    ) -> None:
        self.ocr_analyzer = ocr_analyzer
        self.parser = parser
        self.max_image_bytes = max_image_bytes

    def extract(self, image_bytes: bytes) -> MedicationExtractionResult:
        return self.extract_pages((image_bytes,))

    def extract_pages(
        self,
        image_pages: tuple[bytes, ...],
    ) -> MedicationExtractionResult:
        if not image_pages:
            raise OcrError("약봉투 이미지가 필요합니다.")
        if len(image_pages) > self.MAX_PAGE_COUNT:
            raise OcrError(f"약봉투는 최대 {self.MAX_PAGE_COUNT}장까지 지원합니다.")
        for image_bytes in image_pages:
            if not image_bytes:
                raise OcrError("빈 약봉투 이미지가 포함되어 있습니다.")
            if len(image_bytes) > self.max_image_bytes:
                raise OcrError("약봉투 이미지 크기가 허용 범위를 초과했습니다.")
        extraction = self.parser.parse_images(image_pages)
        return self._build_result(extraction)

    def extract_documents(
        self,
        documents: tuple[OcrDocument, ...],
    ) -> MedicationExtractionResult:
        if not documents:
            raise OcrError("구조화할 약봉투 OCR 결과가 없습니다.")
        if len(documents) > self.MAX_PAGE_COUNT:
            raise OcrError(f"약봉투는 최대 {self.MAX_PAGE_COUNT}장까지 지원합니다.")

        lines = tuple(
            line
            for index, document in enumerate(documents, start=1)
            for line in (f"--- {index}번째 이미지 ---", *document.lines)
        )
        extraction = self.parser.parse(lines)
        return self._build_result(extraction)

    def _build_result(
        self,
        extraction: MedicationExtraction,
    ) -> MedicationExtractionResult:
        """Gemini 구조화 결과를 사용자 검토용 응답으로 만든다."""

        warnings: list[str] = []
        if extraction.prescribed_at is None and extraction.dispensed_at is None:
            warnings.append("처방일 또는 조제일을 인식하지 못했습니다. 직접 입력해 주세요.")
        request_id = str(uuid4())
        logger.info(
            "OCR 처리 메타데이터: request_id=%s ocr_type=MEDICATION "
            "parser_mode=gemini warning_count=%d",
            request_id,
            len(warnings),
        )
        return MedicationExtractionResult(
            request_id=request_id,
            ocr_type=OCR_TYPE_MEDICATION,
            prescribed_at=extraction.prescribed_at,
            dispensed_at=extraction.dispensed_at,
            medical_institution_name=extraction.medical_institution_name,
            pharmacy_name=extraction.pharmacy_name,
            medications=extraction.medications,
            warnings=tuple(warnings),
        )
