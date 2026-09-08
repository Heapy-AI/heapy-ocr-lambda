"""기관별 양식 차이를 합성 데이터로 검증한다. 작성자: 김진우."""

from unittest.mock import Mock

import pytest

from heapy_ocr.app_mapping import map_result
from heapy_ocr.catalog import MASTER_CHECKUP_ITEMS
from heapy_ocr.exceptions import OcrError
from heapy_ocr.gemini import GeminiCheckupParser
from heapy_ocr.rule_parser import CheckupExtraction, RuleBasedCheckupParser
from heapy_ocr.service import HeapyOcrService


def result(rows):
    parsed = GeminiCheckupParser._validate({"items": rows})
    return map_result(HeapyOcrService(Mock(), Mock(), 1000)._build_result(parsed))


@pytest.mark.parametrize("period", ["previous", "unknown", None, "invalid"])
def test_non_current_model_rows_are_not_stored(period):
    assert result([{
        "raw_name": "혈색소", "raw_value": "14.2", "result_period": period,
    }])["items"] == []


@pytest.mark.parametrize("section", ["summary", "trend", "advanced", "risk", "cancer"])
def test_non_result_sections_are_filtered_even_with_current_numbers(section):
    assert result([{
        "raw_name": "혈색소", "raw_value": "14.2",
        "result_period": "current", "section": section,
    }])["items"] == []


def test_comprehensive_common_results_keep_public_contract_and_qualitative_value():
    mapped = result([
        {"raw_name": "Hb(혈색소)", "raw_value": "14.2", "raw_unit": "g/dL",
         "result_period": "current", "section": "general_results"},
        {"raw_name": "U. Protein(요단백)", "raw_value": "음성",
         "result_period": "current", "section": "general_results"},
        {"raw_name": "혈색소", "raw_value": "15.4", "result_period": "previous"},
    ])
    assert set(mapped) == {"measuredAt", "providerName", "items"}
    assert [item["itemCode"] for item in mapped["items"]] == ["HEMOGLOBIN", "URINE_PROTEIN"]
    assert mapped["items"][1]["numericValue"] is None
    assert mapped["items"][1]["value"] == "음성"
    assert all(item["confidence"] is None for item in mapped["items"])


@pytest.mark.parametrize("reverse", [True, False])
def test_explicit_comparison_columns_use_current_value_regardless_of_position(reverse):
    headers = ["이전결과", "금회결과"] if reverse else ["금회결과", "이전결과"]
    values = ["15.4", "14.2"] if reverse else ["14.2", "15.4"]
    parsed = RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS).parse((
        "검진일: 2031-04-12",
        "검사명 | " + " | ".join(headers) + " | 단위",
        "혈색소 | " + " | ".join(values) + " | g/dL",
        "공복혈당 | | | mg/dL",
    ))
    assert parsed.measured_at == "2031-04-12"
    assert [(item.raw_name, item.raw_value) for item in parsed.items] == [("혈색소", "14.2")]


@pytest.mark.parametrize("table", [
    ("검사명 | 결과 | 결과", "혈색소 | 14.2 | 15.4"),
    ("검사명 | 이전결과 | 결과", "혈색소 | 15.4 | 14.2"),
    ("검사명 | 금회결과 | 이전결과", "혈색소 | | 15.4"),
    ("검사항목 금회검사 과거검사", "혈색소 14.2 15.4"),
    ("검사명 | 2028년 | 2031년", "혈색소 | 15.4 | 14.2"),
])
def test_ambiguous_comparison_or_empty_current_does_not_fall_back_to_old_value(table):
    with pytest.raises(OcrError):
        RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS).parse(table)


def test_sections_and_page_boundaries_reset_fallback_state():
    parsed = RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS).parse((
        "--- 1페이지 ---", "종합소견", "혈색소 14.2 g/dL",
        "--- 2페이지 ---", "신체계측 및 기초 검사", "체중 63.4 kg",
        "초음파 검사", "혈색소 16.4 g/dL",
        "혈액검사", "혈색소 14.2 g/dL",
        "--- 3페이지 ---", "이전 결과", "공복혈당 94 98 mg/dL",
        "--- 4페이지 ---", "공복혈당 94 mg/dL",
    ))
    assert [item.raw_value for item in parsed.items] == ["63.4", "14.2", "94"]
    assert [item.source_page for item in parsed.items] == [2, 2, 4]


@pytest.mark.parametrize("dates,expected", [
    (("생년월일 1990-01-01", "출력일 2031-04-17", "검진일 2031-04-12"), "2031-04-12"),
    (("출력일 2031-04-17", "과거 검진일 2028-02-03"), None),
    (("검진일 2031-04-12", "검사일 2031-04-13"), None),
])
def test_fallback_date_requires_unambiguous_examination_label(dates, expected):
    parsed = RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS).parse((*dates, "체중 63.4 kg"))
    assert parsed.measured_at == expected


def test_multi_page_pipeline_merges_repeats_preserves_conflicts_and_conflicting_dates():
    parser = Mock()
    pages = []
    for date, value in [("2031-04-12", "14.2"), ("2031-04-12", "14.2"),
                        ("2031-04-13", "15.4")]:
        pages.append(GeminiCheckupParser._validate({
            "measured_at": date,
            "items": [{"raw_name": "혈색소", "raw_value": value,
                       "raw_unit": "g/dL", "result_period": "current"}],
        }))
    parser.parse_images.side_effect = pages
    service = HeapyOcrService(Mock(), parser, 1000, parser_chunk_page_count=1)
    mapped = map_result(service.extract_pages((b"synthetic-1", b"synthetic-2", b"synthetic-3")))
    assert mapped["measuredAt"] is None
    assert [item["value"] for item in mapped["items"]] == ["14.2", "15.4"]
    assert len({item["fieldKey"] for item in mapped["items"]}) == 2


def test_fifteen_pages_use_existing_bounded_calls_without_external_requests():
    parser = Mock()
    populated = GeminiCheckupParser._validate({
        "items": [{"raw_name": "혈색소", "raw_value": "14.2", "result_period": "current"}],
    })
    parser.parse_images.side_effect = [CheckupExtraction(None, None, ())] * 14 + [populated]
    service = HeapyOcrService(Mock(), parser, 1000, parser_chunk_page_count=1)
    assert len(service.extract_pages((b"synthetic",) * 15).items) == 1
    assert [call.args[1] for call in parser.parse_images.call_args_list] == list(range(1, 16))
