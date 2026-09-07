"""합성 파일과 메모리 저장소로 내부 계약을 검증한다. 작성자: 김진우."""

import copy
import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Lock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from pypdf import PdfWriter

from heapy_ocr.contract import ContractError, Job
from heapy_ocr.files import convert
from heapy_ocr.worker import Worker

NOW = 1_800_000_000
CONTEXT = SimpleNamespace(aws_request_id="실행-1", get_remaining_time_in_millis=lambda: 900000)


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


def image_bytes(format="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", (32, 48), "white").save(stream, format=format)
    return stream.getvalue()


def pdf_bytes(count=2, encrypted=False):
    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=200, height=300)
    if encrypted:
        writer.encrypt("")
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


class MemoryStore:
    bucket = "허용-버킷"

    def __init__(self, data, job):
        self.data = data
        self.version = 1
        self.value = {"request": job.payload, "fingerprint": job.fingerprint, "status": "pending"}
        self.deleted = []
        self.fail_delete = False

    def read(self, key):
        return copy.deepcopy(self.value), str(self.version)

    def cas(self, key, state, etag):
        if etag != str(self.version):
            raise ContractError("STATE_CONFLICT", True)
        self.value = copy.deepcopy(state)
        self.version += 1
        return str(self.version)

    def delete(self, key):
        if self.fail_delete:
            raise RuntimeError("삭제 장애")
        self.deleted.append(key)

    def download(self, job, path):
        path.write_bytes(self.data)


@pytest.fixture
def setup():
    data = image_bytes()
    job_id = str(uuid4())
    event = {
        "contractVersion": "1.0",
        "jobId": job_id,
        "documentType": "health_checkup",
        "inputType": "image",
        "createdAt": iso(NOW),
        "expiresAt": iso(NOW + 1200),
        "source": {
            "bucket": MemoryStore.bucket,
            "key": f"originals/{job_id}/source",
            "extension": "png",
            "sizeBytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    }
    job = Job.parse(event, MemoryStore.bucket, 20_000_000, 1200)
    store = MemoryStore(data, job)
    calls = []

    def run(job, path, deadline, check):
        calls.append(1)
        assert path.exists()
        check()
        return {"pageCount": 1, "result": {"items": []}}

    worker = Worker(store, 20_000_000, 1200, run=run, now=lambda: NOW)
    return worker, store, job, event, calls


@pytest.mark.parametrize("format,extension", [("PNG", "png"), ("JPEG", "jpg"), ("JPEG", "jpeg")])
def test_images(format, extension):
    assert convert(image_bytes(format), extension, 20_000_000)[0].startswith(b"\xff\xd8")


def test_multiple_pdf():
    assert len(convert(pdf_bytes(20), "pdf", 20_000_000)) == 20


@pytest.mark.parametrize(
    "data,extension,code",
    [
        (b"broken", "png", "CORRUPT_FILE"),
        (b"%PDF-broken", "pdf", "CORRUPT_FILE"),
        (image_bytes(), "pdf", "UNSUPPORTED_FORMAT"),
        (image_bytes(), "jpg", "UNSUPPORTED_FORMAT"),
        (pdf_bytes(21), "pdf", "PAGE_LIMIT"),
        (pdf_bytes(encrypted=True), "pdf", "ENCRYPTED_PDF_UNSUPPORTED"),
    ],
)
def test_bad_documents(data, extension, code):
    with pytest.raises(ContractError, match=code):
        convert(data, extension, 20_000_000)


def test_size_limit():
    with pytest.raises(ContractError, match="FILE_LIMIT"):
        convert(image_bytes(), "png", 1)


def test_duplicate_only_processes_once(setup):
    worker, store, job, event, calls = setup
    assert worker.execute(event, CONTEXT)["status"] == "completed"
    assert worker.execute(event, CONTEXT)["status"] == "completed"
    assert len(calls) == 1
    assert worker.read_result(job)["result"] == {"items": []}
    assert store.deleted == [event["source"]["key"]]


def test_expired_read_erases_result(setup):
    worker, store, job, event, _ = setup
    worker.execute(event, CONTEXT)
    worker.now = lambda: NOW + 1200
    with pytest.raises(ContractError, match="EXPIRED"):
        worker.read_result(job)
    assert store.value["result"] is None


def test_late_completion_cannot_resurrect(setup):
    worker, store, job, event, _ = setup

    def run(*args):
        worker.purge(job, "cancelled")
        return {"pageCount": 1, "result": {"items": ["늦은 결과"]}}

    worker.run = run
    assert worker.execute(event, CONTEXT)["status"] == "cancelled"
    assert store.value["result"] is None


@pytest.mark.parametrize("code", ["EXTERNAL_SERVICE_FAILED", "PROCESSING_TIMEOUT", "CORRUPT_FILE"])
def test_failure_cleans_source(setup, code):
    worker, store, _, event, _ = setup

    def run(*args):
        raise ContractError(code)

    worker.run = run
    assert worker.execute(event, CONTEXT)["error"]["code"] == code
    assert store.deleted == [event["source"]["key"]]


def test_cleanup_failure_withholds_result(setup):
    worker, store, _, event, _ = setup
    store.fail_delete = True
    assert worker.execute(event, CONTEXT)["error"]["code"] == "CLEANUP_FAILED"
    assert store.value["result"] is None


@pytest.mark.parametrize(
    "field,value", [("bucket", "외부-버킷"), ("key", "originals/other/source")]
)
def test_arbitrary_source_rejected(setup, field, value):
    worker, store, _, event, calls = setup
    event["source"][field] = value
    with pytest.raises(ContractError, match="SOURCE_NOT_ALLOWED"):
        worker.execute(event, CONTEXT)
    assert calls == [] and store.deleted == []


def test_fingerprint_mismatch(setup):
    worker, store, _, event, _ = setup
    store.value["fingerprint"] = "다른 요청"
    with pytest.raises(ContractError, match="JOB_CONFLICT"):
        worker.execute(event, CONTEXT)


def test_processing_duplicate_returns_receipt(setup):
    worker, store, _, event, calls = setup
    store.value["status"] = "processing"
    assert worker.execute(event, CONTEXT)["status"] == "processing"
    assert not calls


def test_purge_is_idempotent(setup):
    worker, store, job, event, calls = setup
    worker.purge(job, "confirmed")
    worker.purge(job, "confirmed")
    assert worker.execute(event, CONTEXT)["status"] == "confirmed"
    assert store.value["result"] is None and not calls


def test_actual_subprocess_rejects_corrupt_file_without_external_api(setup, tmp_path, monkeypatch):
    worker, _, job, _, _ = setup
    source = tmp_path / "source"
    source.write_bytes(b"broken")
    monkeypatch.setattr("heapy_ocr.worker.load_secrets", lambda: None)
    result = worker.run_process(job, source, NOW + 100, lambda: None)
    assert result == {"errorCode": "CORRUPT_FILE"}


def test_timeout_kills_and_waits_for_child(setup, tmp_path, monkeypatch):
    from unittest.mock import Mock

    worker, _, job, _, _ = setup
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr("heapy_ocr.worker.load_secrets", lambda: None)
    monkeypatch.setattr("heapy_ocr.worker.subprocess.Popen", lambda *args, **kwargs: process)
    with pytest.raises(ContractError, match="PROCESSING_TIMEOUT"):
        worker.run_process(job, tmp_path / "source", NOW - 1, lambda: None)
    process.kill.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)


def test_failed_work_removes_local_directory(setup):
    worker, _, _, event, _ = setup
    paths = []

    def run(job, path, *args):
        paths.append(path.parent)
        raise ContractError("EXTERNAL_SERVICE_FAILED")

    worker.run = run
    worker.execute(event, CONTEXT)
    assert paths and not paths[0].exists()


def test_stale_local_cleanup_only_owns_its_directory(tmp_path, monkeypatch):
    from heapy_ocr.worker import cleanup_stale_local

    owned = tmp_path / "heapy-ocr-old"
    owned.mkdir()
    (owned / "source").write_bytes(b"synthetic")
    untouched = tmp_path / "other-job"
    untouched.mkdir()
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "synthetic")
    monkeypatch.setattr("heapy_ocr.worker.tempfile.gettempdir", lambda: str(tmp_path))
    cleanup_stale_local()
    assert not owned.exists() and untouched.exists()


@pytest.mark.parametrize("expired", [True, False])
def test_janitor_recovers_expired_or_stuck_job(setup, expired):
    from heapy_ocr.janitor import sweep

    worker, store, job, _, _ = setup
    store.owner = "123456789012"
    store.value.update(status="processing", leaseUntil=NOW - 25)
    if expired:
        worker.now = lambda: NOW + 1201

    class Pages:
        def paginate(self, **kwargs):
            return [{"Contents": [{"Key": job.key}]}] if kwargs["Prefix"] == "jobs/" else []

    store.client = SimpleNamespace(get_paginator=lambda name: Pages())
    sweep(worker, CONTEXT)
    assert store.value["status"] == ("expired" if expired else "failed")
    assert store.value["result"] is None and store.deleted


def test_image_expansion_rejected(monkeypatch):
    monkeypatch.setattr("heapy_ocr.files.MAX_PIXELS", 100)
    with pytest.raises(ContractError, match="IMAGE_EXPANSION_LIMIT"):
        convert(image_bytes(), "png", 20_000_000)


def test_future_creation_and_unknown_fields_rejected(setup):
    worker, _, _, event, _ = setup
    event["createdAt"] = iso(NOW + 60)
    with pytest.raises(ContractError, match="INVALID_REQUEST"):
        worker.execute(event, CONTEXT)
    event["createdAt"] = iso(NOW)
    event["password"] = "입력 불가"
    with pytest.raises(ContractError, match="INVALID_REQUEST"):
        worker.execute(event, CONTEXT)


def test_expiration_is_reported_even_if_cleanup_fails(setup):
    worker, store, job, event, calls = setup
    store.fail_delete = True
    worker.now = lambda: NOW + 1201
    with pytest.raises(ContractError, match="EXPIRED"):
        worker.read_result(job)
    assert worker.execute(event, CONTEXT)["error"]["code"] == "EXPIRED"
    assert not calls


def test_expiration_is_reported_even_if_control_is_missing(setup, monkeypatch):
    worker, store, job, event, calls = setup
    worker.now = lambda: NOW + 1201

    def missing(key):
        raise ContractError("JOB_NOT_FOUND")

    monkeypatch.setattr(store, "read", missing)
    with pytest.raises(ContractError, match="EXPIRED"):
        worker.read_result(job)
    assert worker.execute(event, CONTEXT)["status"] == "expired"
    assert not calls


@pytest.mark.parametrize("initial", ["confirmed", "cancelled", "expired"])
def test_purge_preserves_terminal_state(setup, initial):
    worker, store, job, _, _ = setup
    store.value.update(status=initial, result=None)
    previous_version = store.version
    assert worker.purge(job, "cancelled")["status"] == initial
    assert worker.purge(job, "expired")["status"] == initial
    assert store.value["status"] == initial and store.version == previous_version


def test_concurrent_claim_only_processes_once(setup, monkeypatch):
    worker, store, _, event, calls = setup
    barrier, lock = Barrier(2), Lock()
    original_read, original_cas = store.read, store.cas

    def read(key):
        with lock:
            state, etag = original_read(key)
        if state["status"] == "pending":
            barrier.wait(timeout=5)
        return state, etag

    def cas(key, state, etag):
        with lock:
            return original_cas(key, state, etag)

    def invoke():
        try:
            return worker.execute(event, CONTEXT)["status"]
        except ContractError as exc:
            return exc.code

    monkeypatch.setattr(store, "read", read)
    monkeypatch.setattr(store, "cas", cas)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: invoke(), range(2)))
    assert sorted(results) == ["STATE_CONFLICT", "completed"]
    assert len(calls) == 1


@pytest.mark.parametrize("fail_delete", [False, True])
def test_janitor_recovers_orphan_and_signals_delete_failure(setup, fail_delete):
    from heapy_ocr.janitor import sweep

    worker, store, job, _, _ = setup
    store.owner = "123456789012"
    store.fail_delete = fail_delete
    old_key = job.payload["source"]["key"]
    recent_key = f"originals/{uuid4()}/source"

    class Pages:
        def paginate(self, **kwargs):
            assert kwargs["ExpectedBucketOwner"] == store.owner
            if kwargs["Prefix"] == "jobs/":
                return []
            return [{"Contents": [
                {"Key": old_key, "LastModified": datetime.fromtimestamp(NOW - 1201, UTC)},
                {"Key": recent_key, "LastModified": datetime.fromtimestamp(NOW, UTC)},
            ]}]

    store.client = SimpleNamespace(get_paginator=lambda name: Pages())
    if fail_delete:
        with pytest.raises(ContractError, match="SWEEP_FAILED"):
            sweep(worker, CONTEXT)
    else:
        assert sweep(worker, CONTEXT) == {"deleted": 1, "failed": 0}
        assert store.deleted == [old_key]
