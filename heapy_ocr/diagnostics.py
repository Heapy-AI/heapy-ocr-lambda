"""원문 없이 외부 호출 진단만 자식에서 부모로 전달한다. 작성자: 김진우."""

import json
import logging
import os
import ssl
import time
import urllib.error
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

from heapy_ocr.exceptions import ExternalServiceError

LIMIT = 32768
HTTP_STATUS = ContextVar("ocr_http_status", default=None)
CODES = {
    "OK",
    "TIMEOUT",
    "AUTH_FAILED",
    "RATE_LIMITED",
    "HTTP_ERROR",
    "SERVER_ERROR",
    "CONNECTION_ERROR",
    "TLS_ERROR",
    "RESPONSE_FORMAT",
    "CONFIGURATION_REQUIRED",
    "UNEXPECTED_ERROR",
    "EMPTY_RESULT",
}


def classify(error):
    """예외 문자열·응답 본문을 읽지 않고 타입과 상태만 분류한다."""
    if isinstance(error, ExternalServiceError) and error.diagnostic_code in CODES:
        return error.diagnostic_code, error.http_status
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, urllib.error.HTTPError):
            status = current.code
            if status in (408, 504):
                return "TIMEOUT", status
            if status in (401, 403):
                return "AUTH_FAILED", status
            if status == 429:
                return "RATE_LIMITED", status
            return ("SERVER_ERROR" if status >= 500 else "HTTP_ERROR"), status
        if isinstance(current, TimeoutError):
            return "TIMEOUT", None
        if isinstance(current, ssl.SSLError):
            return "TLS_ERROR", None
        if isinstance(current, urllib.error.URLError):
            if isinstance(current.reason, BaseException):
                code, status = classify(current.reason)
                if code in ("TIMEOUT", "TLS_ERROR"):
                    return code, status
            return "CONNECTION_ERROR", None
        if isinstance(current, json.JSONDecodeError | UnicodeError):
            return "RESPONSE_FORMAT", None
        current = current.__cause__
    if isinstance(error, ExternalServiceError):
        return "RESPONSE_FORMAT", None
    return "UNEXPECTED_ERROR", None


def observe(provider):
    """API 키·요청·예외 메시지는 직렬화하지 않는다."""

    def decorate(function):
        @wraps(function)
        def wrapped(self, *args, **kwargs):
            started = time.monotonic()
            token = HTTP_STATUS.set(None)
            code, status = "OK", None
            try:
                return function(self, *args, **kwargs)
            except Exception as error:
                code, status = classify(error)
                if not self.api_key:
                    code, status = "CONFIGURATION_REQUIRED", None
                raise
            finally:
                status = status if status is not None else HTTP_STATUS.get()
                HTTP_STATUS.reset(token)
                event = dict(
                    provider=provider,
                    code=code,
                    httpStatus=status,
                    durationMs=max(0, int((time.monotonic() - started) * 1000)),
                )
                record(event)

        return wrapped

    return decorate


def mark_status(response):
    """실제로 받은 HTTP 상태만 기록한다."""
    status = getattr(response, "status", None)
    if type(status) is int and 100 <= status <= 599:
        HTTP_STATUS.set(status)


def record(event):
    location = os.environ.get("OCR_DIAGNOSTICS_PATH")
    if not location:
        return
    try:
        path = Path(location)
        line = (json.dumps(event, separators=(",", ":")) + "\n").encode()
        if path.exists() and path.stat().st_size + len(line) > LIMIT:
            return
        with path.open("ab") as stream:
            stream.write(line)
    except OSError:
        # 진단 파일 장애로 OCR 결과를 바꾸지 않는다.
        pass


def emit(path, logger, job_id):
    """자식이 쓴 값도 허용 목록과 크기를 검증한 뒤에만 로그로 남긴다."""
    if not path.exists():
        return
    with path.open("rb") as stream:
        data = stream.read(LIMIT)
    for index, line in enumerate(data.splitlines(), 1):
        try:
            event = json.loads(line)
            if set(event) != {"provider", "code", "httpStatus", "durationMs"}:
                continue
            if event["provider"] not in ("gemini", "gemini_medication", "vision"):
                continue
            if event["code"] not in CODES:
                continue
            status, duration = event["httpStatus"], event["durationMs"]
            if status is not None and (type(status) is not int or not 100 <= status <= 599):
                continue
            if type(duration) is not int or not 0 <= duration <= 900000:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        logger.log(
            logging.INFO if event["code"] == "OK" else logging.WARNING,
            "OCR_EXTERNAL_CALL jobId=%s provider=%s callIndex=%d "
            "code=%s httpStatus=%s durationMs=%d",
            job_id,
            event["provider"],
            index,
            event["code"],
            status,
            duration,
        )
