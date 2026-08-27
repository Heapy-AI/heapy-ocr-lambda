"""건강검진 항목 매칭 테스트.

작성자: 김진우
"""

from heapy_ocr.matcher import CheckupItemMatcher
from heapy_ocr.models import MasterCheckupItem, RawCheckupItem

CATALOG = (
    MasterCheckupItem("FASTING_GLUCOSE", "공복혈당", "mg/dL"),
    MasterCheckupItem("SYSTOLIC_BP", "수축기혈압", "mmHg"),
    MasterCheckupItem("DIASTOLIC_BP", "이완기혈압", "mmHg"),
    MasterCheckupItem("AST", "에이에스티(AST)", "U/L"),
)


def test_공복시혈당_별칭을_마스터에_연결한다() -> None:
    matcher = CheckupItemMatcher(CATALOG)

    result = matcher.match(
        RawCheckupItem("공복 시 혈당", "108", "mg/dL", "정상B"),
        0.97,
    )

    assert result.item_code == "FASTING_GLUCOSE"
    assert result.value == "108"
    assert result.printed_status == "정상B"
    assert result.needs_review is False


def test_알수없는_항목은_저장코드를_만들지_않는다() -> None:
    matcher = CheckupItemMatcher(CATALOG)

    result = matcher.match(RawCheckupItem("확인 불가 항목", "12"), 0.99)

    assert result.item_code is None
    assert result.needs_review is True
