"""비공개 Invoke 작업과 취소·회수 처리. 작성자: 김진우."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import boto3
from botocore.config import Config

from heapy_ocr.contract import VERSION, ContractError, Job, response, timestamp
from heapy_ocr.diagnostics import emit
from heapy_ocr.review_metrics import emit_review_metrics
from heapy_ocr.storage import Store

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Worker:
    def __init__(self, store: Store, max_bytes: int, max_ttl: int, run=None, now=time.time):
        if max_bytes not in (20_000_000, 20 * 1024 * 1024) or max_ttl <= 0:
            raise ContractError("CONFIGURATION_REQUIRED")
        self.store = store
        self.max_bytes = max_bytes
        self.max_ttl = max_ttl
        self.run = run or self.run_process
        self.now = now

    def job(self, event: dict) -> Job:
        return Job.parse(event, self.store.bucket, self.max_bytes, self.max_ttl)

    def state(self, job: Job) -> tuple[dict, str]:
        state, etag = self.store.read(job.key)
        if state.get("request") != job.payload or state.get("fingerprint") != job.fingerprint:
            raise ContractError("JOB_CONFLICT")
        return state, etag

    def check_active(self, job: Job, etag: str) -> None:
        if self.now() >= job.expires:
            raise ContractError("EXPIRED")
        state, current = self.state(job)
        if current != etag or state["status"] != "processing":
            raise ContractError("STATE_CONFLICT")

    def execute(self, event: dict, context) -> dict:
        job = self.job(event)
        if timestamp(event["createdAt"]) > self.now() + 30:
            raise ContractError("INVALID_REQUEST")
        if self.now() >= job.expires:
            self.expire(job)
            return response(job.id, "expired", "EXPIRED")
        state, etag = self.state(job)
        if state["status"] != "pending":
            return self.receipt(job, state)
        deadline = min(
            self.now() + 780,
            job.expires,
            self.now() + context.get_remaining_time_in_millis() / 1000 - 20,
        )
        if deadline <= self.now():
            raise ContractError("TIME_BUDGET", True)
        state = {
            **state,
            "status": "processing",
            "leaseUntil": deadline,
            "executionId": context.aws_request_id,
        }
        etag = self.store.cas(job.key, state, etag)
        result = None
        code = None
        started = self.now()
        try:
            with tempfile.TemporaryDirectory(prefix="heapy-ocr-") as directory:
                path = Path(directory) / "source"
                self.store.download(job, path)
                self.check_active(job, etag)
                result = self.run(job, path, deadline, lambda: self.check_active(job, etag))
                if "errorCode" in result:
                    raise ContractError(result["errorCode"])
                self.check_active(job, etag)
        except ContractError as exc:
            code = exc.code
        except Exception:
            code = "PROCESSING_FAILED"
        finally:
            # 성공 결과도 원본 삭제가 확인되기 전에는 공개하지 않는다.
            try:
                self.store.delete(job.payload["source"]["key"])
            except Exception:
                code = "CLEANUP_FAILED"
        if self.now() >= job.expires:
            code = "EXPIRED"
        final = {
            **state,
            "status": "completed"
            if code is None
            else ("expired" if code == "EXPIRED" else "failed"),
            "result": result if code is None else None,
            "errorCode": code,
        }
        try:
            self.store.cas(job.key, final, etag)
            if code is None:
                emit_review_metrics(logger, job.id, result)
        except ContractError as exc:
            if exc.code != "STATE_CONFLICT":
                raise
            # 취소·회수의 상태를 덮어쓰지 않는다.
            final, _ = self.state(job)
        logger.info(
            "jobId=%s durationMs=%d code=%s",
            job.id,
            int((self.now() - started) * 1000),
            code or "OK",
        )
        if code:
            logger.warning("OCR_FAILURE jobId=%s code=%s", job.id, code)
        return self.receipt(job, final)

    @staticmethod
    def receipt(job: Job, state: dict) -> dict:
        result = state.get("result") or {}
        return response(
            job.id,
            state["status"],
            state.get("errorCode"),
            pageCount=result.get("pageCount"),
            expiresAt=job.payload["expiresAt"],
        )

    def read_result(self, job: Job) -> dict:
        if self.now() >= job.expires:
            self.expire(job)
            raise ContractError("EXPIRED")
        state, _ = self.state(job)
        return {
            **self.receipt(job, state),
            "result": (state.get("result") or {}).get("result")
            if state["status"] == "completed"
            else None,
        }

    def expire(self, job: Job) -> None:
        """회수 장애와 관계없이 만료된 내용의 조회·재실행을 차단한다."""
        try:
            self.purge(job, "expired")
        except Exception:
            logger.warning("OCR_FAILURE jobId=%s code=CLEANUP_FAILED", job.id)

    def purge(self, job: Job, reason: str) -> dict:
        if reason not in ("cancelled", "confirmed", "expired"):
            raise ContractError("INVALID_REQUEST")
        for _ in range(5):
            state, etag = self.state(job)
            try:
                terminal = state["status"] in ("confirmed", "cancelled", "expired")
                final_status = state["status"] if terminal else reason
                if not terminal or state.get("result") is not None:
                    self.store.cas(
                        job.key,
                        {**state, "status": final_status, "result": None, "errorCode": None},
                        etag,
                    )
                self.store.delete(job.payload["source"]["key"])
                return response(job.id, final_status)
            except ContractError as exc:
                if exc.code != "STATE_CONFLICT":
                    raise
        raise ContractError("STATE_CONFLICT", True)

    def run_process(self, job: Job, path: Path, deadline: float, check) -> dict:
        load_secrets()
        output = path.parent / "result.json"
        command = [
            sys.executable,
            "-m",
            "heapy_ocr.processor",
            str(path),
            str(output),
            job.payload["source"]["extension"],
            job.payload["documentType"],
        ]
        child_env = dict(os.environ)
        child_env["MAX_UPLOAD_BYTES"] = str(self.max_bytes)
        diagnostics = path.parent / "diagnostics.jsonl"
        child_env["OCR_DIAGNOSTICS_PATH"] = str(diagnostics)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_env,
            creationflags=flags,
        )
        next_check = 0
        try:
            while process.poll() is None:
                if self.now() >= deadline:
                    raise ContractError("PROCESSING_TIMEOUT")
                if self.now() >= next_check:
                    check()
                    next_check = self.now() + 2
                time.sleep(0.1)
            if process.returncode != 0 or not output.exists():
                raise ContractError("PROCESSING_FAILED")
            if output.stat().st_size > 512 * 1024:
                raise ContractError("RESULT_LIMIT")
            return json.loads(output.read_text(encoding="utf-8"))
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            try:
                emit(diagnostics, logger, job.id)
            except OSError:
                logger.warning("OCR_FAILURE jobId=%s code=DIAGNOSTICS_UNAVAILABLE", job.id)


def build_worker() -> Worker:
    config = Config(
        connect_timeout=3, read_timeout=5, retries={"mode": "standard", "total_max_attempts": 2}
    )
    return Worker(
        Store(
            boto3.client("s3", config=config),
            os.environ["OCR_BUCKET"],
            os.environ["AWS_ACCOUNT_ID"],
        ),
        int(os.environ["MAX_UPLOAD_BYTES"]),
        int(os.environ["MAX_RESULT_TTL_SECONDS"]),
    )


def load_secrets() -> None:
    client = boto3.client(
        "secretsmanager",
        config=Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 2}),
    )
    secret = json.loads(
        client.get_secret_value(SecretId=os.environ["OCR_SECRET_ARN"])["SecretString"]
    )
    if not secret.get("GEMINI_API_KEY"):
        raise ContractError("CONFIGURATION_REQUIRED")
    for name in ("GEMINI_API_KEY", "GOOGLE_VISION_API_KEY"):
        os.environ[name] = secret.get(name, "")


def cleanup_stale_local() -> None:
    """Lambda 실행환경 재사용 시 이전 강제 종료의 전용 임시 폴더만 회수한다."""
    if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return
    root = Path(tempfile.gettempdir()).resolve()
    for path in root.glob("heapy-ocr-*"):
        if path.is_dir() and not path.is_symlink() and path.resolve().parent == root:
            shutil.rmtree(path)


def lambda_handler(event, context):
    job_id = None
    try:
        cleanup_stale_local()
        if event == {"contractVersion": VERSION, "operation": "selftest"}:
            from heapy_ocr.selftest import selftest

            return selftest()
        worker = build_worker()
        if isinstance(event, dict) and event.get("operation") in ("read", "purge"):
            if set(event) != {"contractVersion", "operation", "request", "reason"}:
                raise ContractError("INVALID_REQUEST")
            if event["contractVersion"] != VERSION:
                raise ContractError("INVALID_REQUEST")
            job = worker.job(event["request"])
            job_id = job.id
            if event["operation"] == "read":
                return worker.read_result(job)
            return worker.purge(job, event["reason"])
        job = worker.job(event)
        job_id = job.id
        return worker.execute(event, context)
    except ContractError as exc:
        logger.warning("OCR_FAILURE jobId=%s code=%s", job_id, exc.code)
        return response(job_id, "failed", exc.code, exc.retryable)
    except Exception:
        logger.error("jobId=%s code=INFRASTRUCTURE_FAILED", job_id)
        return response(job_id, "failed", "INFRASTRUCTURE_FAILED", True)
