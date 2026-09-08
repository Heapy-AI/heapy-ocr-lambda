"""외부 오류 분류와 민감정보 차단 검증. 작성자: 김진우."""

import io
import json
import logging
import urllib.error
from unittest.mock import patch

import pytest

from heapy_ocr.diagnostics import emit
from heapy_ocr.exceptions import ExternalServiceError
from heapy_ocr.gemini import GeminiCheckupParser


@pytest.mark.parametrize(
    "failure,code,status",
    [
        (TimeoutError("비밀 원문"), "TIMEOUT", None),
        (urllib.error.URLError(TimeoutError("비밀 원문")), "TIMEOUT", None),
        (urllib.error.URLError("비밀 원문"), "CONNECTION_ERROR", None),
        *[
            (
                urllib.error.HTTPError(
                    "비밀 URL", number, "비밀 원문", {}, io.BytesIO(b"PRIVATE_KEY_HEALTH_DATA")
                ),
                code,
                number,
            )
            for number, code in [
                (401, "AUTH_FAILED"),
                (403, "AUTH_FAILED"),
                (429, "RATE_LIMITED"),
                (503, "SERVER_ERROR"),
                (504, "TIMEOUT"),
                (400, "HTTP_ERROR"),
            ]
        ],
    ],
)
def test_classification_and_redaction(tmp_path, monkeypatch, caplog, failure, code, status):
    path = tmp_path / "diagnostics.jsonl"
    monkeypatch.setenv("OCR_DIAGNOSTICS_PATH", str(path))
    parser = GeminiCheckupParser("PRIVATE_KEY_HEALTH_DATA", "test", 60)
    with patch("urllib.request.urlopen", side_effect=failure), pytest.raises(ExternalServiceError):
        parser.parse_images((b"\xff\xd8\xffPRIVATE_KEY_HEALTH_DATA",))
    event = json.loads(path.read_text())
    assert event["code"] == code and event["httpStatus"] == status
    assert event["durationMs"] >= 0
    with caplog.at_level(logging.INFO):
        emit(path, logging.getLogger("diagnostic-test"), "synthetic-job")
    assert "PRIVATE_KEY_HEALTH_DATA" not in path.read_text() + caplog.text
    assert "비밀" not in path.read_text() + caplog.text
    assert "jobId=synthetic-job" in caplog.text
    assert "code=" + code in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff",
        b"{}",
        json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}).encode(),
    ],
)
def test_malformed_response(tmp_path, monkeypatch, body):
    path = tmp_path / "diagnostics.jsonl"
    monkeypatch.setenv("OCR_DIAGNOSTICS_PATH", str(path))
    with (
        patch("urllib.request.urlopen", return_value=io.BytesIO(body)),
        pytest.raises(ExternalServiceError),
    ):
        GeminiCheckupParser("key", "test", 60).parse_images((b"\xff\xd8\xfftest",))
    assert json.loads(path.read_text())["code"] == "RESPONSE_FORMAT"


def test_fallback_retains_failure_and_success(tmp_path, monkeypatch, caplog):
    from heapy_ocr.diagnostics import observe

    path = tmp_path / "diagnostics.jsonl"
    monkeypatch.setenv("OCR_DIAGNOSTICS_PATH", str(path))

    class Fallback:
        api_key = "private"

        @observe("vision")
        def analyze(self):
            return "PRIVATE_HEALTH_TEXT"

    with (
        patch("urllib.request.urlopen", side_effect=TimeoutError()),
        pytest.raises(ExternalServiceError),
    ):
        GeminiCheckupParser("key", "test", 60).parse_images((b"\xff\xd8\xfftest",))
    Fallback().analyze()
    with caplog.at_level(logging.INFO):
        emit(path, logging.getLogger("diagnostic-test"), "synthetic-job")
    assert "provider=gemini callIndex=1 code=TIMEOUT" in caplog.text
    assert "provider=vision callIndex=2 code=OK" in caplog.text
    assert "PRIVATE_HEALTH_TEXT" not in caplog.text


def test_parent_rejects_injected_fields(tmp_path, caplog):
    path = tmp_path / "diagnostics.jsonl"
    path.write_text(
        json.dumps(
            dict(
                provider="gemini",
                code="OK",
                httpStatus=200,
                durationMs=1,
                body="PRIVATE_HEALTH_TEXT",
            )
        )
        + "\n"
    )
    with caplog.at_level(logging.INFO):
        emit(path, logging.getLogger("diagnostic-test"), "job")
    assert not caplog.records


@pytest.mark.parametrize("returncode", [0, -9])
def test_worker_forwards_child_diagnostics_on_exit(tmp_path, monkeypatch, caplog, returncode):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from heapy_ocr.contract import ContractError
    from heapy_ocr.worker import Worker

    monkeypatch.setattr("heapy_ocr.worker.load_secrets", lambda: None)
    process = Mock(returncode=returncode)
    process.poll.return_value = returncode

    def start(*args, **kwargs):
        from pathlib import Path

        assert kwargs["stdout"] == kwargs["stderr"] == -3
        Path(kwargs["env"]["OCR_DIAGNOSTICS_PATH"]).write_text(
            json.dumps(dict(provider="gemini", code="TIMEOUT", httpStatus=None, durationMs=60001))
            + "\n"
        )
        (tmp_path / "result.json").write_text('{"errorCode":"EXTERNAL_SERVICE_FAILED"}')
        return process

    monkeypatch.setattr("heapy_ocr.worker.subprocess.Popen", start)
    job = SimpleNamespace(
        id="synthetic-job",
        payload={"source": {"extension": "pdf"}, "documentType": "health_checkup"},
    )
    worker = Worker(Mock(), 20000000, 600)
    with caplog.at_level(logging.INFO):
        if returncode == 0:
            assert worker.run_process(job, tmp_path / "source", 100, lambda: None) == {
                "errorCode": "EXTERNAL_SERVICE_FAILED"
            }
        else:
            with pytest.raises(ContractError, match="PROCESSING_FAILED"):
                worker.run_process(job, tmp_path / "source", 100, lambda: None)
    assert "code=TIMEOUT httpStatus=None durationMs=60001" in caplog.text


def test_bounded_record_and_vision_embedded_error(tmp_path, monkeypatch):
    from heapy_ocr.diagnostics import LIMIT, classify, record
    from heapy_ocr.google_vision import GoogleVisionAnalyzer

    path = tmp_path / "diagnostics.jsonl"
    monkeypatch.setenv("OCR_DIAGNOSTICS_PATH", str(path))
    for _ in range(500):
        record(dict(provider="gemini", code="OK", httpStatus=200, durationMs=1))
    assert path.stat().st_size <= LIMIT
    with pytest.raises(ExternalServiceError) as caught:
        GoogleVisionAnalyzer._parse_response(
            {"responses": [{"error": {"code": 8, "message": "PRIVATE_HEALTH_TEXT"}}]}
        )
    assert classify(caught.value) == ("RATE_LIMITED", 200)
    assert "PRIVATE_HEALTH_TEXT" not in str(caught.value)
