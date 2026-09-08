"""체크박스의 실시대상과 실제 결과를 구분하는 합성 검증. 작성자: 김진우."""

import pytest

from heapy_ocr.gemini import GeminiCheckupParser


def parse(value, **context):
    return GeminiCheckupParser._validate({"items": [{
        "raw_name": "합성 선택검사", "raw_value": value, **context,
    }]}).items


@pytest.mark.parametrize("value", ["체크", "체크됨", "해당", "선택됨"])
def test_check_and_eligibility_markers_are_not_results(value):
    assert not parse(value, eligibility="eligible", result_evidence="selected_option")


@pytest.mark.parametrize("eligibility", ["ineligible", "unknown", None])
def test_unperformed_or_uncertain_eligibility_overrides_printed_normal(eligibility):
    assert not parse("정상", eligibility=eligibility, result_evidence="selected_option")


def test_eligible_without_selected_result_is_not_a_measurement():
    assert not parse("정상", eligibility="eligible", result_evidence="unknown")


def test_actual_qualitative_selected_result_survives():
    items = parse("합성 기관 평가", eligibility="eligible", result_evidence="selected_option")
    assert len(items) == 1 and items[0].raw_value == "합성 기관 평가"


def test_numeric_result_survives_without_judgment_and_check_marker_is_not_status():
    items = parse("14.6", eligibility="not_applicable", result_evidence="printed_value",
                  printed_status="체크")
    assert len(items) == 1 and items[0].raw_value == "14.6"
    assert items[0].printed_status is None


def test_document_title_is_not_provider_and_summary_flags_are_not_items():
    parsed = GeminiCheckupParser._validate({
        "hospital_name": "건강검진 결과통보서",
        "items": [{"raw_name": "일반 질환의심", "raw_value": "선택"},
                  {"raw_name": "안내: 검사를 받으셨습니다", "raw_value": "완료"}],
    })
    assert parsed.hospital_name is None and not parsed.items


def test_provider_name_is_not_replaced_with_invented_name():
    parsed = GeminiCheckupParser._validate({"hospital_name": "합성검증의원", "items": []})
    assert parsed.hospital_name == "합성검증의원"
