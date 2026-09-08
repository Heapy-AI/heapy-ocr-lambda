"""건강검진 요청 크기 조정과 페이지 번호 보존 검증. 작성자: 김진우."""

from unittest.mock import Mock

from heapy_ocr.config import Settings
from heapy_ocr.models import RawCheckupItem
from heapy_ocr.rule_parser import CheckupExtraction
from heapy_ocr.service import HeapyOcrService


def test_default_single_page_preserves_timeout_and_page_numbers(monkeypatch):
    monkeypatch.delenv("GEMINI_PAGES_PER_REQUEST", raising=False)
    monkeypatch.delenv("GEMINI_TIMEOUT_SECONDS", raising=False)
    settings = Settings.from_env()
    assert settings.gemini_pages_per_request == 1
    assert settings.gemini_timeout_seconds == 60
    parser = Mock()
    parser.parse_images.return_value = CheckupExtraction(
        None, None, (RawCheckupItem("공복혈당", "95", "mg/dL"),)
    )
    analyzer = Mock()
    service = HeapyOcrService(analyzer, parser, 1024, settings.gemini_pages_per_request)
    pages = (b"page-one", b"page-two", b"page-three", b"page-four")
    service.extract_pages(pages)
    assert [call.args for call in parser.parse_images.call_args_list] == [
        ((page,), number) for number, page in enumerate(pages, 1)
    ]
    analyzer.analyze.assert_not_called()


def test_explicit_page_setting_is_preserved(monkeypatch):
    monkeypatch.setenv("GEMINI_PAGES_PER_REQUEST", "2")
    assert Settings.from_env().gemini_pages_per_request == 2
