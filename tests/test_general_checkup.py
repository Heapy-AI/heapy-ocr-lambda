"""실제 개인정보를 복제하지 않는 일반검진 계약 검증. 작성자: 김진우."""

from unittest.mock import Mock

import pytest

from heapy_ocr.app_mapping import map_result
from heapy_ocr.catalog import MASTER_CHECKUP_ITEMS
from heapy_ocr.exceptions import OcrError
from heapy_ocr.gemini import _RESPONSE_SCHEMA, GeminiCheckupParser
from heapy_ocr.general_checkup import general_lines
from heapy_ocr.rule_parser import RuleBasedCheckupParser
from heapy_ocr.service import HeapyOcrService


def test_general_response_preserves_numbers_and_qualitative_results():
    extraction = GeminiCheckupParser._validate({
        "measured_at": "2024-02-03", "hospital_name": "합성검진기관",
        "items": [
            {"raw_name": "수축기혈압", "raw_value": "118", "raw_unit": "mmHg"},
            {"raw_name": "이완기혈압", "raw_value": "76", "raw_unit": "mmHg"},
            {"raw_name": "시력(좌)", "raw_value": "0.8"},
            {"raw_name": "시력(우)", "raw_value": "1.2"},
            {"raw_name": "청력(좌)", "raw_value": "정상"},
            {"raw_name": "요단백", "raw_value": "음성"},
            {"raw_name": "총콜레스테롤", "raw_value": "비해당"},
        ],
    })
    result = map_result(HeapyOcrService(Mock(), Mock(), 1000)._build_result(extraction))
    assert set(result) == {"measuredAt", "providerName", "items"}
    items = result["items"]
    assert [item["numericValue"] for item in items] == [118, 76, 0.8, 1.2, None, None]
    assert items[0]["itemCode"] == "SYSTOLIC_BP"
    assert items[1]["itemCode"] == "DIASTOLIC_BP"
    assert items[2]["itemCode"] == "VISUAL_ACUITY_LEFT"
    assert items[3]["itemCode"] == "VISUAL_ACUITY_RIGHT"
    hearing = next(item for item in items if item["itemCode"] == "HEARING_GENERAL_LEFT")
    assert hearing["numericValue"] is None and hearing["unit"] is None
    assert hearing["value"] == "정상"
    assert all(item["confidence"] is None and item["status"] is None for item in items)


def test_fallback_excludes_cancer_and_risk_pages_without_fixed_page_numbers():
    lines = (
        "--- 1페이지 ---", "위암 검진 결과통보서", "혈색소 99 g/dL",
        "--- 2페이지 ---", "일반건강검진 결과통보서", "공복혈당 88 mg/dL",
        "--- 3페이지 ---", "심뇌혈관질환 위험평가", "공복혈당 77 mg/dL",
    )
    assert general_lines(lines) == lines[3:6]
    parsed = RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS).parse(lines)
    assert len(parsed.items) == 1 and parsed.items[0].raw_value == "88"


def test_fallback_does_not_guess_checkbox_selection():
    with pytest.raises(OcrError):
        RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS).parse((
            "공복혈당 □ 정상 100미만 ■ 공복혈당장애 의심 110",))


def test_general_prompt_and_schema_are_used_for_images(monkeypatch):
    parser = GeminiCheckupParser("synthetic", "synthetic", 1)
    request = Mock(return_value={"items": []})
    monkeypatch.setattr(parser, "_request_json", request)
    assert parser.parse_images((b"synthetic",), 4).items == ()
    prompt = request.call_args.args[0]
    assert "4페이지" in prompt and "암검진" in prompt and "체크박스" in prompt
    assert set(_RESPONSE_SCHEMA["properties"]) == {"measured_at", "hospital_name", "items"}


def test_service_factory_has_no_demo_dependency(monkeypatch):
    from heapy_ocr.factory import build_medication_service, build_service

    monkeypatch.setenv("GEMINI_API_KEY", "synthetic")
    monkeypatch.setenv("GEMINI_MODEL", "synthetic")
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "")
    assert build_service().parser.model == "synthetic"
    assert build_medication_service().parser.model == "synthetic"
