"""Gemini 이미지 직접 처리 흐름 테스트.

작성자: 김진우
"""

from __future__ import annotations

from typing import NoReturn

from heapy_ocr.gemini import _request_payload
from heapy_ocr.medication import MedicationExtraction
from heapy_ocr.medication_service import MedicationOcrService
from heapy_ocr.models import CheckupSummary, ParsedMedication, RawCheckupItem
from heapy_ocr.rule_parser import CheckupExtraction
from heapy_ocr.service import HeapyOcrService

JPEG_BYTES = b"\xff\xd8\xfftest"


class FailingAnalyzer:
    """직접 처리 성공 시 Vision이 호출되지 않는지 확인한다."""

    def analyze(self, image_bytes: bytes) -> NoReturn:
        del image_bytes
        raise AssertionError("Gemini 직접 처리 중 Vision이 호출됐습니다.")


class CheckupImageParser:
    """건강검진 Gemini 응답을 대신하는 테스트 파서."""

    def parse_images(
        self,
        image_pages: tuple[bytes, ...],
        first_page_number: int,
    ) -> CheckupExtraction:
        assert image_pages == (JPEG_BYTES,)
        assert first_page_number == 1
        return CheckupExtraction(
            measured_at="2024-01-09",
            hospital_name="테스트병원",
            items=(
                RawCheckupItem("공복혈당", "91", "mg/dL", "정상", 2),
                RawCheckupItem(
                    "병원특수혈관탄성검사",
                    "표재성 위염",
                    source_page=4,
                    detail_data={"interpretation": "표재성 위염 소견"},
                ),
            ),
            parser_mode="gemini",
            document_type="COMPREHENSIVE",
            summary=CheckupSummary(overall_status="정상"),
        )


class MedicationImageParser:
    """약봉투 Gemini 응답을 대신하는 테스트 파서."""

    def parse_images(
        self,
        image_pages: tuple[bytes, ...],
    ) -> MedicationExtraction:
        assert image_pages == (JPEG_BYTES,)
        return MedicationExtraction(
            prescribed_at=None,
            dispensed_at="2026-08-26",
            medical_institution_name=None,
            pharmacy_name="테스트약국",
            medications=(
                ParsedMedication("테스트정", "테스트정", None, "1", "정", 2, 3),
            ),
        )


def test_gemini_payload_contains_page_image() -> None:
    payload = _request_payload("테스트", (JPEG_BYTES,))

    parts = payload["contents"][0]["parts"]
    assert parts[0] == {"text": "테스트"}
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
    assert parts[1]["inlineData"]["data"]


def test_health_checkup_uses_gemini_without_vision() -> None:
    service = HeapyOcrService(
        ocr_analyzer=FailingAnalyzer(),
        parser=CheckupImageParser(),  # type: ignore[arg-type]
        max_image_bytes=1024,
    )

    result = service.extract_pages((JPEG_BYTES,)).to_dict()

    assert result["record"]["document_type"] == "COMPREHENSIVE"
    assert result["record"]["summary_data"]["overall_status"] == "정상"
    assert result["results"][0]["item_code"] == "FASTING_GLUCOSE"
    assert result["results"][0]["value_numeric"] == 91
    assert result["results"][0]["value_text"] is None
    assert result["results"][0]["source_page"] == 2
    assert result["results"][1]["item_code"] is None
    assert result["results"][1]["value_numeric"] is None
    assert result["results"][1]["value_text"] == "표재성 위염"
    assert result["results"][1]["detail_data"]["interpretation"] == "표재성 위염 소견"


def test_medication_uses_gemini_without_vision() -> None:
    service = MedicationOcrService(
        ocr_analyzer=FailingAnalyzer(),
        parser=MedicationImageParser(),  # type: ignore[arg-type]
        max_image_bytes=1024,
    )

    result = service.extract_pages((JPEG_BYTES,)).to_dict()

    assert result["pharmacy_name"] == "테스트약국"
    assert result["medications"][0]["frequency_per_day"] == 2
