"""백엔드 전용 OCR 서비스 구성. 작성자: 김진우."""

from heapy_ocr.catalog import MASTER_CHECKUP_ITEMS
from heapy_ocr.config import Settings
from heapy_ocr.gemini import GeminiCheckupParser
from heapy_ocr.google_vision import GoogleVisionAnalyzer
from heapy_ocr.medication import GeminiMedicationParser
from heapy_ocr.medication_service import MedicationOcrService
from heapy_ocr.rule_parser import RuleBasedCheckupParser
from heapy_ocr.service import HeapyOcrService


def build_service() -> HeapyOcrService:
    """환경변수와 외부 서비스 어댑터로 OCR 서비스를 생성한다."""
    settings = Settings.from_env()
    return HeapyOcrService(
        ocr_analyzer=GoogleVisionAnalyzer(
            settings.google_vision_api_key,
            settings.external_timeout_seconds,
        ),
        parser=GeminiCheckupParser(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.gemini_timeout_seconds,
        ),
        max_image_bytes=settings.max_image_bytes,
        parser_chunk_page_count=settings.gemini_pages_per_request,
        fallback_parser=(
            RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS)
            if settings.google_vision_api_key
            else None
        ),
    )


def build_medication_service() -> MedicationOcrService:
    """환경변수와 외부 서비스 어댑터로 약봉투 OCR 서비스를 생성한다."""

    settings = Settings.from_env()
    return MedicationOcrService(
        ocr_analyzer=GoogleVisionAnalyzer(
            settings.google_vision_api_key,
            settings.external_timeout_seconds,
        ),
        parser=GeminiMedicationParser(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.gemini_timeout_seconds,
        ),
        max_image_bytes=settings.max_image_bytes,
    )


