"""건강검진 OCR 애플리케이션 서비스.

작성자: 김진우
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from heapy_ocr.exceptions import OcrError
from heapy_ocr.gemini import GeminiCheckupParser
from heapy_ocr.matcher import CheckupItemMatcher
from heapy_ocr.models import ExtractionResult, ParsedCheckupItem
from heapy_ocr.supabase import SupabaseGateway
from heapy_ocr.textract import TextractAnalyzer


class HeapyOcrService:
    """OCR 추출과 사용자 확인 후 저장 흐름을 조정한다."""

    def __init__(
        self,
        textract: TextractAnalyzer,
        parser: GeminiCheckupParser,
        supabase: SupabaseGateway,
        max_image_bytes: int,
    ) -> None:
        self.textract = textract
        self.parser = parser
        self.supabase = supabase
        self.max_image_bytes = max_image_bytes

    def extract(self, image_bytes: bytes, access_token: str) -> ExtractionResult:
        if not image_bytes:
            raise OcrError("건강검진 결과지 이미지가 필요합니다.")
        if len(image_bytes) > self.max_image_bytes:
            raise OcrError("건강검진 결과지 이미지 크기가 허용 범위를 초과했습니다.")

        catalog = self.supabase.get_catalog(access_token)
        document = self.textract.analyze(image_bytes)
        extraction = self.parser.parse(document.lines)
        matcher = CheckupItemMatcher(catalog)
        items = tuple(
            matcher.match(raw_item, document.average_confidence)
            for raw_item in extraction.items
        )

        warnings: list[str] = []
        review_count = sum(item.needs_review for item in items)
        if review_count:
            warnings.append(f"{review_count}개 항목은 저장 전에 확인이 필요합니다.")
        if extraction.measured_at is None:
            warnings.append("검진일을 인식하지 못했습니다. 직접 입력해 주세요.")
        return ExtractionResult(
            request_id=str(uuid4()),
            ocr_type="HEALTH_CHECKUP",
            measured_at=extraction.measured_at,
            hospital_name=extraction.hospital_name,
            items=items,
            warnings=tuple(warnings),
        )

    def confirm_and_save(
        self,
        access_token: str,
        measured_at: str,
        items: tuple[ParsedCheckupItem, ...],
    ) -> str:
        try:
            normalized_date = date.fromisoformat(measured_at).isoformat()
        except (TypeError, ValueError) as exc:
            raise OcrError("검진일은 YYYY-MM-DD 형식이어야 합니다.") from exc
        if not items:
            raise OcrError("저장할 건강검진 항목이 없습니다.")

        catalog_codes = {
            item.item_code for item in self.supabase.get_catalog(access_token)
        }
        seen_codes: set[str] = set()
        for item in items:
            if not item.item_code or item.item_code not in catalog_codes:
                raise OcrError(f"확인되지 않은 검사항목입니다: {item.raw_name}")
            if item.item_code in seen_codes:
                raise OcrError(f"검사항목이 중복되었습니다: {item.item_code}")
            if not item.value.strip():
                raise OcrError(f"검사 결과값이 비어 있습니다: {item.item_code}")
            seen_codes.add(item.item_code)
        return self.supabase.save_checkup(
            access_token,
            normalized_date,
            items,
        )
