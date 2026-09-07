"""외부 서비스·S3·배포 경계의 합성 검증. 작성자: 김진우."""

import io
from types import SimpleNamespace
from unittest.mock import Mock

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from heapy_ocr.app_mapping import map_result, safe_numeric
from heapy_ocr.contract import ContractError, encode
from heapy_ocr.exceptions import ExternalServiceError
from heapy_ocr.models import CheckupSummary, RawCheckupItem
from heapy_ocr.ocr import OcrDocument
from heapy_ocr.rule_parser import CheckupExtraction, RuleBasedCheckupParser
from heapy_ocr.service import HeapyOcrService
from heapy_ocr.storage import Store
from scripts.deploy import deploy


@pytest.mark.parametrize(
    "value,expected", [("3,5", None), ("<5", None), ("1,234.5", 1234.5), ("-1.2", -1.2)]
)
def test_numeric_does_not_guess_ambiguous_values(value, expected):
    assert safe_numeric(value) == expected


def test_partial_fallback_keeps_successful_pages():
    parser = Mock()
    parser.parse_images.side_effect = [
        CheckupExtraction(
            None, None, (RawCheckupItem("공복혈당", "90", "mg/dL"),), parser_mode="gemini"
        ),
        ExternalServiceError("외부 시간 초과"),
    ]
    analyzer = Mock()
    analyzer.analyze.return_value = OcrDocument("신장 170 cm", ("신장 170 cm",), 0.9)
    fallback = Mock(spec=RuleBasedCheckupParser)
    fallback.parse.return_value = CheckupExtraction(
        None, None, (RawCheckupItem("신장", "170", "cm"),)
    )
    service = HeapyOcrService(analyzer, parser, 1000, 1, fallback)
    result = service.extract_pages(("첫 페이지".encode(), "둘째 페이지".encode()))
    assert len(result.items) == 2
    analyzer.analyze.assert_called_once_with("둘째 페이지".encode())
    assert result.parser_mode == "gemini_with_rule_fallback"


def test_mapping_no_fake_confidence_or_unit_conversion():
    extraction = CheckupExtraction(
        None,
        None,
        (
            RawCheckupItem("공복혈당", "5.5", "mmol/L"),
            RawCheckupItem("합성특수검사", "음성", None, None),
        ),
        summary=CheckupSummary(overall_status="합성 소견"),
    )
    service = HeapyOcrService(Mock(), Mock(), 1000)
    mapped = map_result(service._build_result(extraction))
    matched, unmatched = mapped["items"]
    assert matched["itemCode"] == "FASTING_GLUCOSE"
    assert matched["unit"] == "mmol/L" and matched["numericValue"] == 5.5
    assert matched["confidence"] is None and matched["status"] is None
    assert unmatched["itemCode"] is None and unmatched["numericValue"] is None
    assert unmatched["value"] == "음성"
    assert mapped["measuredAt"] is None
    assert "summary_data" not in mapped


def s3():
    return boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
    )


def test_s3_conditional_write_and_conflict():
    client = s3()
    store = Store(client, "synthetic-bucket", "123456789012")
    args = {
        **store.args("jobs/test.json"),
        "Body": encode({"status": "processing"}),
        "IfMatch": '"v1"',
        "ServerSideEncryption": "AES256",
        "ContentType": "application/json",
        "CacheControl": "no-store",
    }
    with Stubber(client) as stub:
        stub.add_response("put_object", {"ETag": '"v2"'}, args)
        assert store.cas("jobs/test.json", {"status": "processing"}, '"v1"') == '"v2"'
        stub.add_client_error(
            "put_object", "PreconditionFailed", http_status_code=412, expected_params=args
        )
        with pytest.raises(ContractError, match="STATE_CONFLICT"):
            store.cas("jobs/test.json", {"status": "processing"}, '"v1"')


def test_s3_actual_body_size_and_digest(tmp_path):
    client = s3()
    store = Store(client, "synthetic-bucket", "123456789012")
    job = SimpleNamespace(
        payload={"source": {"key": "originals/test/source", "sizeBytes": 2, "sha256": "0" * 64}}
    )
    with Stubber(client) as stub:
        stub.add_response(
            "get_object",
            {"ContentLength": 2, "Body": StreamingBody(io.BytesIO(b"ab"), 2)},
            store.args("originals/test/source"),
        )
        with pytest.raises(ContractError, match="SOURCE_MISMATCH"):
            store.download(job, tmp_path / "source")


def test_failed_promotion_rolls_back_all_promoted_functions(monkeypatch):
    client = Mock()
    client.get_alias.return_value = {"FunctionVersion": "1", "RevisionId": "기존"}
    client.get_function_configuration.return_value = {"RevisionId": "현재"}
    client.publish_version.return_value = {"Version": "2"}
    calls = []

    def smoke(client, name, qualifier):
        calls.append((name, qualifier))
        if (name, qualifier) == ("worker", "2"):
            raise RuntimeError("새 버전 실패")

    monkeypatch.setattr("scripts.deploy.smoke", smoke)
    with pytest.raises(RuntimeError, match="새 버전 실패"):
        deploy(client, ["janitor", "worker"], "이미지-digest", "커밋")
    assert client.update_alias.call_args.kwargs["FunctionName"] == "janitor"
    assert client.update_alias.call_args.kwargs["FunctionVersion"] == "1"
