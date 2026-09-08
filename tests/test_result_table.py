"""실제 문서 값을 복제하지 않는 합성 검진 표 검증. 작성자: 김진우."""

from unittest.mock import Mock

import pytest

from heapy_ocr.app_mapping import map_result
from heapy_ocr.catalog import MASTER_CHECKUP_ITEMS
from heapy_ocr.gemini import GeminiCheckupParser
from heapy_ocr.matcher import CheckupItemMatcher
from heapy_ocr.models import RawCheckupItem
from heapy_ocr.rule_parser import CheckupExtraction, RuleBasedCheckupParser
from heapy_ocr.service import HeapyOcrService


def parse(rows):
    return GeminiCheckupParser._validate({"items": rows})


def mapped(extraction):
    return map_result(HeapyOcrService(Mock(), Mock(), 1000)._build_result(extraction))["items"]


def row(name, value="합성 결과", **kwargs):
    return dict(raw_name=name, raw_value=value, **kwargs)


def test_title_and_advice_are_not_measurements():
    rows = [
        row(name)
        for name in (
            "관리가 필요합니다",
            "판정",
            "빈혈",
            "당뇨병",
            "과거병력",
            "예방접종",
            "흡연",
            "신체활동",
            "약물치료",
        )
    ]
    rows += [
        row(
            "공복혈당",
            "93",
            raw_unit="mg/dL",
            row_kind="measurement",
            section="general_results",
            value_origin="result",
        )
    ]
    items = mapped(parse(rows))
    assert len(items) == 1
    assert items[0]["itemCode"] == "FASTING_GLUCOSE" and items[0]["numericValue"] == 93


@pytest.mark.parametrize(
    "metadata",
    [
        {"section": "summary"},
        {"section": "risk"},
        {"section": "cancer"},
        {"value_origin": "reference"},
        {"value_origin": "target"},
        {"performed": False},
        {"row_kind": "heading"},
        {"row_kind": "guidance"},
    ],
)
def test_result_like_numbers_in_wrong_cells_are_excluded(metadata):
    assert not parse([row("공복혈당", "93", **metadata)]).items


@pytest.mark.parametrize(
    "label,order,expected",
    [
        ("혈압", "systolic_diastolic", [137, 89]),
        ("혈압", "diastolic_systolic", [89, 137]),
        ("혈압(수축기/이완기)", None, [137, 89]),
    ],
)
def test_bp_split_requires_order_and_unit(label, order, expected):
    items = mapped(
        parse(
            [
                row(
                    label,
                    "137/89",
                    raw_unit="mmHg",
                    component_order=order,
                    printed_status="기관 원문 판정",
                    source_page=7,
                )
            ]
        )
    )
    assert [item["itemCode"] for item in items] == ["SYSTOLIC_BP", "DIASTOLIC_BP"]
    assert [item["numericValue"] for item in items] == expected
    assert all(item["status"] == "기관 원문 판정" and item["confidence"] is None for item in items)


def test_bp_without_order_is_preserved_unmatched():
    items = mapped(parse([row("혈압", "137/89", raw_unit="mmHg")]))
    assert len(items) == 1 and items[0]["itemCode"] is None
    assert items[0]["value"] == "137/89"


def test_identical_duplicates_merge_but_conflicts_survive():
    values = [
        row("혈색소", "12.7", raw_unit="g/dL", printed_status="기관 A", source_page=2),
        row("헤모글로빈", "12.7", raw_unit="g/dL", printed_status="기관 A", source_page=5),
        row("혈색소", "13.8", raw_unit="g/dL", printed_status="기관 A", source_page=6),
        row("혈색소", "12.7", raw_unit="g/dL", printed_status="기관 B", source_page=7),
    ]
    items = mapped(parse(values))
    assert len(items) == 3
    assert len({item["fieldKey"] for item in items}) == 3
    assert {item["value"] for item in items} == {"12.7", "13.8"}


@pytest.mark.parametrize(
    "name,unit,code",
    [
        ("혈청 크레아티닌", "mg/dL", "SERUM_CREATININE"),
        ("신사구체여과율(e-GFR)", "mL/min/1.73m²", "EGFR"),
        ("에이에스티(AST)", "IU/L", "AST"),
        ("에이엘티(ALT)", "IU/L", "ALT"),
        ("감마지티피(γGTP)", "IU/L", "GAMMA_GTP"),
        ("고밀도 콜레스테롤(HDL)", "mg/dL", "HDL_CHOLESTEROL"),
        ("혈색소", "mmHg", None),
        ("혈당", "mg/dL", None),
    ],
)
def test_alias_semantics_and_units(name, unit, code):
    item = CheckupItemMatcher(MASTER_CHECKUP_ITEMS).match(RawCheckupItem(name, "7", unit), 1)
    assert item.item_code == code
    assert item.raw_unit == unit


def test_real_qualitative_and_assessment_results_survive():
    items = mapped(
        parse(
            [
                row("요단백", "음성", row_kind="qualitative"),
                row("흉부방사선촬영", "합성 기관 판정", row_kind="qualitative"),
                row(
                    "생활습관평가", "합성 평가 결과", row_kind="assessment", section="questionnaire"
                ),
                row(
                    "문진·진찰 및 상담",
                    "합성 상담 결과",
                    row_kind="assessment",
                    section="questionnaire",
                ),
                row("청력(좌)", "정상", row_kind="qualitative"),
                row("우울증 선별검사", "합성 정성 판정", row_kind="assessment"),
            ]
        )
    )
    assert [item["itemCode"] for item in items[:4]] == [
        "URINE_PROTEIN",
        "CHEST_XRAY",
        "LIFESTYLE_ASSESSMENT",
        "MEDICAL_INTERVIEW_CONSULTATION",
    ]
    assert items[4]["itemCode"] == "HEARING_GENERAL_LEFT" and items[4]["numericValue"] is None
    assert items[5]["itemCode"] is None


def test_qualitative_hearing_never_becomes_frequency_measurement():
    matcher = CheckupItemMatcher(MASTER_CHECKUP_ITEMS)
    for label in ("청력 1000Hz(좌)", "HEARING_1000HZ_LEFT"):
        assert matcher.match(RawCheckupItem(label, "정상"), 1).item_code is None


def test_synthetic_table_reads_result_column_not_disease_or_reference():
    # 의도적으로 참고치 열을 실제 결과보다 앞에 둔다.
    table = (
        "--- 7페이지 ---",
        "일반건강검진 결과통보서",
        "질환 구분 | 검사명 | 참고치 | 단위 | 실제 결과 | 기관 판정",
        "빈혈 | 혈색소 | 11~17 | g/dL | 12.7 | 합성 판정",
        "당뇨병 | 공복혈당 | 99미만 | mg/dL | 93 | 합성 판정",
        "고혈압 | 혈압(수축기/이완기) | 119/79 | mmHg | 137/89 | 합성 판정",
        "기타 | 판정 | | | 관리가 필요합니다 |",
    )
    extraction = RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS).parse(table)
    assert all(item.source_page == 7 for item in extraction.items)
    items = mapped(extraction)
    assert [item["numericValue"] for item in items] == [12.7, 93, 137, 89]


def test_flat_fallback_does_not_join_name_across_page_or_reference():
    lines = (
        "--- 1페이지 ---",
        "혈색소",
        "--- 2페이지 ---",
        "19.1 g/dL",
        "공복혈당 참고치 99미만",
        "흡연: 공복혈당 91 관련 안내",
        "체중 58 kg",
    )
    items = RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS).parse(lines).items
    assert len(items) == 1 and items[0].raw_name == "체중"


def test_filter_applies_to_fallback_and_unknown_real_test_stays():
    extraction = CheckupExtraction(
        None,
        None,
        (
            RawCheckupItem("관리가 필요합니다", "합성 문장"),
            RawCheckupItem("미지원합성검사", "정성 결과"),
        ),
    )
    items = mapped(extraction)
    assert len(items) == 1 and items[0]["itemCode"] is None


def test_lifestyle_assessment_requires_result_context():
    assert not parse([row("생활습관", "합성 문장")]).items
    items = mapped(
        parse(
            [
                row(
                    "생활습관",
                    "합성 기관 평가",
                    row_kind="assessment",
                    value_origin="result",
                    section="questionnaire",
                )
            ]
        )
    )
    assert items[0]["itemCode"] == "LIFESTYLE_ASSESSMENT"
    assert items[0]["value"] == "합성 기관 평가"


def test_fallback_preserves_compound_units_and_never_fills_missing_unit():
    items = (
        RuleBasedCheckupParser(MASTER_CHECKUP_ITEMS)
        .parse(
            (
                "체질량지수 22.3 kg/m2",
                "신사구체여과율 84 mL/min/1.73m2",
                "혈색소 12.7",
            )
        )
        .items
    )
    assert [item.raw_unit for item in items] == ["kg/m2", "mL/min/1.73m2", None]
