"""백엔드 전용 OCR 내부 계약. 작성자: 김진우."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

VERSION = "1.0"
MAX_RESULT_BYTES = 512 * 1024


class ContractError(Exception):
    """원문을 포함하지 않는 내부 오류."""

    def __init__(self, code: str, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def encode(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()


def timestamp(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.timestamp()
    except (AttributeError, ValueError, TypeError) as exc:
        raise ContractError("INVALID_REQUEST") from exc


@dataclass(frozen=True)
class Job:
    payload: dict

    @classmethod
    def parse(cls, payload: dict, bucket: str, max_bytes: int, max_ttl: int) -> Job:
        try:
            required = {
                "contractVersion",
                "jobId",
                "documentType",
                "inputType",
                "source",
                "createdAt",
                "expiresAt",
            }
            if not isinstance(payload, dict) or set(payload) != required:
                raise ValueError
            if len(encode(payload)) > 8192:
                raise ValueError
            if payload["contractVersion"] != VERSION:
                raise ValueError
            job_id = payload["jobId"]
            if str(UUID(job_id)) != job_id:
                raise ValueError
            if payload["documentType"] not in ("health_checkup", "medication"):
                raise ValueError
            source = payload["source"]
            if set(source) != {"bucket", "key", "extension", "sizeBytes", "sha256"}:
                raise ValueError
            extension = source["extension"]
            if extension not in ("jpg", "jpeg", "png", "pdf"):
                raise ContractError("UNSUPPORTED_FORMAT")
            if source["bucket"] != bucket or source["key"] != f"originals/{job_id}/source":
                raise ContractError("SOURCE_NOT_ALLOWED")
            if type(source["sizeBytes"]) is not int or not 0 < source["sizeBytes"] <= max_bytes:
                raise ContractError("FILE_LIMIT")
            if not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
                raise ValueError
            if payload["inputType"] not in ("camera", "image", "pdf"):
                raise ValueError
            if (extension == "pdf") != (payload["inputType"] == "pdf"):
                raise ValueError
            lifetime = timestamp(payload["expiresAt"]) - timestamp(payload["createdAt"])
            if not 0 < lifetime <= max_ttl:
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ContractError("INVALID_REQUEST") from exc
        return cls(payload)

    @property
    def id(self) -> str:
        return self.payload["jobId"]

    @property
    def expires(self) -> float:
        return timestamp(self.payload["expiresAt"])

    @property
    def key(self) -> str:
        return f"jobs/{self.id}.json"

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(encode(self.payload)).hexdigest()


def response(
    job_id: str | None, status: str, code: str | None = None, retryable: bool = False, **fields
) -> dict:
    return {
        "contractVersion": VERSION,
        "jobId": job_id,
        "status": status,
        "error": None
        if code is None
        else {"contractVersion": VERSION, "code": code, "retryable": retryable},
        **fields,
    }
