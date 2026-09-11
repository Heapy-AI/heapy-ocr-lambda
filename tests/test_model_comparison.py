"""모델 비교 채점이 오류를 성공으로 집계하지 않는지 검증. 작성자: 김진우."""

from scripts.compare_ocr_models import score


def test_wrong_value_and_unexpected_result_are_penalized():
    payload = {
        "items": [
            {"raw_name": "혈색소", "raw_value": "15.8"},
            {"raw_name": "총콜레스테롤", "raw_value": "177"},
        ]
    }
    metrics = score(payload, {("HEMOGLOBIN", "14.6")}, {})
    assert metrics["correct"] == 0
    assert metrics["missing"] == 1
    assert metrics["extra"] == 2


def test_value_correct_does_not_hide_missing_institution_judgment():
    payload = {"items": [{"raw_name": "혈색소", "raw_value": "14.6"}]}
    metrics = score(payload, {("HEMOGLOBIN", "14.6")}, {"HEMOGLOBIN": "정상"})
    assert metrics["correct"] == 1
    assert metrics["status_correct"] == 0
