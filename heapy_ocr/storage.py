"""업무 DB와 분리된 S3 임시 저장소. 작성자: 김진우."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from botocore.exceptions import ClientError

from heapy_ocr.contract import MAX_RESULT_BYTES, ContractError, Job, encode


class Store:
    def __init__(self, client, bucket: str, owner: str):
        self.client = client
        self.bucket = bucket
        self.owner = owner

    def args(self, key: str) -> dict:
        return {"Bucket": self.bucket, "Key": key, "ExpectedBucketOwner": self.owner}

    def read(self, key: str) -> tuple[dict, str]:
        try:
            result = self.client.get_object(**self.args(key))
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise ContractError("JOB_NOT_FOUND") from exc
            raise
        with result["Body"] as stream:
            data = stream.read(MAX_RESULT_BYTES + 1)
        if len(data) > MAX_RESULT_BYTES:
            raise ContractError("RESULT_LIMIT")
        return json.loads(data), result["ETag"]

    def cas(self, key: str, state: dict, etag: str) -> str:
        data = encode(state)
        if len(data) > MAX_RESULT_BYTES:
            raise ContractError("RESULT_LIMIT")
        try:
            result = self.client.put_object(
                **self.args(key),
                Body=data,
                IfMatch=etag,
                ServerSideEncryption="AES256",
                ContentType="application/json",
                CacheControl="no-store",
            )
            return result["ETag"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] in (
                "PreconditionFailed",
                "ConditionalRequestConflict",
            ):
                raise ContractError("STATE_CONFLICT", True) from exc
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(**self.args(key))

    def download(self, job: Job, path: Path) -> None:
        source = job.payload["source"]
        result = self.client.get_object(**self.args(source["key"]))
        digest = hashlib.sha256()
        size = 0
        with result["Body"] as stream, path.open("wb") as output:
            if result["ContentLength"] != source["sizeBytes"]:
                raise ContractError("SOURCE_MISMATCH")
            while chunk := stream.read(min(65536, source["sizeBytes"] - size + 1)):
                size += len(chunk)
                if size > source["sizeBytes"]:
                    raise ContractError("FILE_LIMIT")
                digest.update(chunk)
                output.write(chunk)
        if size != source["sizeBytes"] or digest.hexdigest() != source["sha256"]:
            raise ContractError("SOURCE_MISMATCH")
