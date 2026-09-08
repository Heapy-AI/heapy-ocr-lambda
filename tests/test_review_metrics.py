"""개선 지표의 내용 유출·실패 격리 검증. 작성자: 김진우."""

from unittest.mock import Mock

from heapy_ocr.review_metrics import emit_review_metrics

JOB = "11111111-1111-4111-8111-111111111111"


def envelope():
    return {
        "pageCount": 1,
        "result": {
            "schemaVersion": 2,
            "items": [],
            "findings": [],
            "overallOpinions": [],
            "reviewRequired": [
                {
                    "reason": "uncertain_classification",
                    "text": "합성 비밀이름 내시경: 합성 비밀소견",
                },
                {"reason": "unmatched_item", "text": "혈압: 123mmHg / 81mmHg"},
            ],
        },
    }


def test_metrics_never_include_content_or_untrusted_fields():
    logger = Mock()
    data = envelope()
    data["result"]["secret"] = "금지 원문"
    emit_review_metrics(logger, JOB, data)
    message = logger.info.call_args.args[2]
    assert '"excludedCandidateCount":2' in message
    assert '"procedure_label":1' in message
    assert '"unit_in_pair":1' in message
    for value in ("비밀", "금지", "123", "81mmHg", "text", "secret"):
        assert value not in message


def test_untrusted_reason_is_not_logged():
    logger = Mock()
    data = envelope()
    data["result"]["reviewRequired"][0]["reason"] = "개인정보 주입"
    emit_review_metrics(logger, JOB, data)
    logger.info.assert_not_called()


def test_logging_failure_does_not_interrupt_results():
    logger = Mock()
    logger.info.side_effect = OSError("합성 오류")
    emit_review_metrics(logger, JOB, envelope())


def test_legacy_medication_and_invalid_job_are_not_logged():
    logger = Mock()
    emit_review_metrics(logger, JOB, {"result": {"items": []}})
    emit_review_metrics(logger, "금지 파일 경로", envelope())
    logger.info.assert_not_called()
