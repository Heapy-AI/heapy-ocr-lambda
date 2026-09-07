"""강제 종료·만료 뒤 민감 임시 객체 회수. 작성자: 김진우."""

import time

from heapy_ocr.contract import ContractError
from heapy_ocr.worker import build_worker


def sweep(worker, context) -> dict:
    store = worker.store
    counts = {"deleted": 0, "failed": 0}
    for prefix in ("jobs/", "originals/"):
        paginator = store.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=store.bucket, Prefix=prefix, ExpectedBucketOwner=store.owner
        ):
            for entry in page.get("Contents", []):
                if context.get_remaining_time_in_millis() < 15000:
                    raise ContractError("SWEEP_INCOMPLETE", True)
                key = entry["Key"]
                try:
                    if prefix == "originals/":
                        if entry["LastModified"].timestamp() + worker.max_ttl < worker.now():
                            store.delete(key)
                            counts["deleted"] += 1
                        continue
                    state, etag = store.read(key)
                    job = worker.job(state["request"])
                    if key != job.key:
                        raise ContractError("SOURCE_NOT_ALLOWED")
                    if worker.now() >= job.expires:
                        worker.purge(job, "expired")
                        # 모든 실행이 끝난 뒤에만 제어 객체를 제거한다.
                        if worker.now() > job.expires + 900:
                            store.delete(key)
                            counts["deleted"] += 1
                    elif (
                        state["status"] == "processing" and worker.now() > state["leaseUntil"] + 20
                    ):
                        store.cas(
                            key,
                            {
                                **state,
                                "status": "failed",
                                "result": None,
                                "errorCode": "PROCESSING_TIMEOUT",
                            },
                            etag,
                        )
                        store.delete(job.payload["source"]["key"])
                    elif state["status"] in ("failed", "cancelled", "confirmed", "completed"):
                        store.delete(job.payload["source"]["key"])
                except Exception:
                    counts["failed"] += 1
    if counts["failed"]:
        # EventBridge 재시도와 CloudWatch 오류 지표에 실패를 남기되 원문은 출력하지 않는다.
        raise ContractError("SWEEP_FAILED", True)
    return counts


def lambda_handler(event, context):
    if event == {"contractVersion": "1.0", "operation": "selftest"}:
        return {"contractVersion": "1.0", "status": "ok"}
    started = time.monotonic()
    result = sweep(build_worker(), context)
    return {**result, "durationMs": int((time.monotonic() - started) * 1000)}
