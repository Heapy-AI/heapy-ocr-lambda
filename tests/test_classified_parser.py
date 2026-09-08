"""합성 검진 표·기관 소견 분류의 회귀 검증. 작성자: 김진우."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from heapy_ocr.app_mapping import map_classified_result, map_result
from heapy_ocr.classified_parser import ClassifiedCheckupParser
from heapy_ocr.exceptions import ExternalServiceError, OcrError
from heapy_ocr.factory import build_service
from heapy_ocr.gemini import GeminiCheckupParser, _request_payload
from heapy_ocr.service import HeapyOcrService


def payload():
    return {
        "measured_at": None, "hospital_name": None,
        "items": [
            {"raw_name": "혈색소", "raw_value": "13.7", "raw_unit": "g/dL"},
            {"raw_name": "청력(좌)", "raw_value": "정상"},
            {"raw_name": "관리가 필요합니다", "raw_value": "안내 문장"},
            {"raw_name": "미지원 합성 검사", "raw_value": "합성 결과"},
        ],
        "findings": [{"exam_name": "위내시경", "exam_type": "upper_gi_endoscopy",
                      "text": "합성 기관 관찰 내용.\n합성 추적 권고.",
                      "body_site": None, "method": None, "performed_at": None}],
        "overall_opinions": [{"exam_name": "종합소견", "exam_type": None,
                              "text": "합성 기관의 회차 권고."}],
        "review_required": [],
    }


def mapped(data):
    parsed = ClassifiedCheckupParser._validate(data)
    service = HeapyOcrService(Mock(), Mock(), 1000)
    return map_classified_result(service._build_result(service._merge_extractions([parsed])))


def test_mixed_report_separates_items_findings_opinions_and_unmatched():
    result = mapped(payload())
    assert result["schemaVersion"] == 2
    assert [i["itemCode"] for i in result["items"]] == ["HEMOGLOBIN", "HEARING_GENERAL_LEFT"]
    assert result["items"][0]["confidence"] is None
    assert len(result["findings"]) == len(result["overallOpinions"]) == 1
    assert "\n" in result["findings"][0]["text"]
    assert result["findings"][0]["summary"] is None
    assert result["reviewRequired"][0]["reason"] == "unmatched_item"
    assert len(result["reviewRequired"]) == 1
    assert result["findings"][0]["bodySite"] is None


@pytest.mark.parametrize("keep", ["findings", "overall_opinions", "review_required"])
def test_no_numeric_item_required(keep):
    data = payload()
    data["items"] = []
    data["review_required"] = [{"text": "합성 결과 후보", "reason": "uncertain_classification"}]
    for field in ("findings", "overall_opinions", "review_required"):
        if field != keep:
            data[field] = []
    assert mapped(data)["items"] == []


def test_ids_are_stable_across_mapping_and_chunk_merge_does_not_merge_distinct_exams():
    data = payload()
    second = deepcopy(data["findings"][0])
    second.update(body_site="합성 부위 B", performed_at="2025-02-04")
    data["findings"].append(second)
    first = ClassifiedCheckupParser._validate(data)
    another_page = ClassifiedCheckupParser._validate(data)
    service = HeapyOcrService(Mock(), Mock(), 1000)
    result = service._build_result(service._merge_extractions([first, another_page]))
    one = map_classified_result(result)
    assert one == map_classified_result(result)
    assert len({f["findingId"] for f in one["findings"]}) == 4
    assert len(one["items"]) == 2


def test_endoscopy_leaked_into_items_requires_review_not_automatic_finding():
    data = payload()
    data["findings"] = []
    data["items"].append({"raw_name": "위내시경 소견", "raw_value": "합성 관찰 문장"})
    result = mapped(data)
    assert result["findings"] == []
    assert any(r["reason"] == "uncertain_classification" for r in result["reviewRequired"])
    assert all(i["itemCode"] != "UPPER_GI_ENDOSCOPY" for i in result["items"])


@pytest.mark.parametrize("mutation", [
    {"exam_type": "invented"}, {"text": " "}, {"text": "가" * 12001},
    {"text": "😀" * 6001}, {"performed_at": "2025-02-30"},
    {"performed_at": "20250203"}, {"patient_name": "금지 필드"},
    {"summary": {"text": "생성 요약"}},
])
def test_invalid_findings_fail_without_truncation_or_arbitrary_fields(mutation):
    data = payload()
    data["findings"][0].update(mutation)
    with pytest.raises(ExternalServiceError):
        mapped(data)


def test_overall_opinion_cannot_acquire_inferred_exam_context():
    data = payload()
    data["overall_opinions"][0]["body_site"] = "추정 부위"
    with pytest.raises(ExternalServiceError):
        mapped(data)


def test_limits_apply_after_page_merge():
    part = ClassifiedCheckupParser._validate(payload())
    service = HeapyOcrService(Mock(), Mock(), 1000)
    combined = service._build_result(service._merge_extractions([part] * 21))
    with pytest.raises(OcrError):
        map_classified_result(combined)


def test_classified_fallback_never_completes_without_lost_findings():
    cause = ExternalServiceError("외부 시간 초과")
    parser = ClassifiedCheckupParser("", "synthetic", 60)
    parser.parse_images = Mock(side_effect=cause)
    fallback = Mock()
    service = HeapyOcrService(Mock(), parser, 1000, fallback_parser=fallback)
    with pytest.raises(ExternalServiceError):
        service.extract_pages((b"synthetic",))
    fallback.parse.assert_not_called()


def test_legacy_schema_and_response_remain_unchanged():
    old = GeminiCheckupParser._validate(payload())
    result = HeapyOcrService(Mock(), Mock(), 1000)._build_result(old)
    assert set(map_result(result)) == {"measuredAt", "providerName", "items"}
    assert "findings" not in GeminiCheckupParser.response_schema["properties"]
    schema = _request_payload("합성", response_schema=ClassifiedCheckupParser.response_schema)
    assert "findings" in schema["generationConfig"]["responseJsonSchema"]["required"]


def test_classified_text_path_keeps_procedure_context():
    parser = ClassifiedCheckupParser("synthetic", "synthetic", 60)
    parser._request_json = Mock(return_value=payload())
    parser.parse(("위암 검진 결과통보서", "위내시경", "합성 소견"))
    prompt = parser._request_json.call_args.args[0]
    assert "위내시경" in prompt and "합성 소견" in prompt
    assert "items만 포함" not in prompt


def test_factory_keeps_new_path_explicit_and_default_legacy():
    assert type(build_service().parser) is GeminiCheckupParser
    assert type(build_service(classified=True).parser) is ClassifiedCheckupParser


def test_current_row_values_and_conflicts_survive_findings_classification():
    data = payload()
    data["items"] = [
        {"raw_name": "공복혈당", "raw_value": "91", "result_period": "previous"},
        {"raw_name": "공복혈당", "raw_value": "97", "result_period": "current"},
        {"raw_name": "공복혈당", "raw_value": "98", "result_period": "current"},
        {"raw_name": "혈압", "raw_value": "124/79", "raw_unit": "mmHg",
         "component_order": "systolic_diastolic"},
    ]
    result = mapped(data)
    assert [(i["itemCode"], i["value"]) for i in result["items"]] == [
        ("FASTING_GLUCOSE", "97"), ("FASTING_GLUCOSE", "98"),
        ("SYSTOLIC_BP", "124"), ("DIASTOLIC_BP", "79"),
    ]
    assert len({i["fieldKey"] for i in result["items"]}) == 4


@pytest.mark.parametrize("name, expected", [
    ("흉부촬영", True), ("흉부 X선", True),
    ("흉부방사선 직접촬영(PA)", True),
])
def test_chest_direction_is_not_inferred(name, expected):
    data = payload()
    data["items"] = [{"raw_name": name, "raw_value": "합성 정성 결과"}]
    result = mapped(data)
    assert bool(result["items"]) is expected
    if expected:
        assert result["items"][0]["itemCode"] == ("CHEST_XRAY_PA" if "PA" in name else "CHEST_XRAY")
    else:
        assert result["reviewRequired"][0]["reason"] == "unmatched_item"


def test_provider_schema_simplification_keeps_server_count_limit():
    data = payload()
    data["findings"] *= 51
    with pytest.raises(ExternalServiceError):
        mapped(data)
