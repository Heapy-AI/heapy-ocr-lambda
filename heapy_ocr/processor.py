"""시간·메모리를 격리한 OCR 자식 프로세스. 작성자: 김진우."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from heapy_ocr.app_mapping import map_classified_result, map_result
from heapy_ocr.contract import MAX_RESULT_BYTES, ContractError, encode


def process(source: Path, extension: str, document_type: str, max_bytes: int) -> dict:
    from heapy_ocr.factory import build_medication_service, build_service
    from heapy_ocr.files import convert

    pages = convert(source.read_bytes(), extension, max_bytes)
    if document_type == "health_checkup":
        version = os.environ.get("CHECKUP_SCHEMA_VERSION", "2")
        if version not in {"1", "2"}:
            raise ContractError("INVALID_SCHEMA_VERSION")
        result = build_service(classified=version == "2").extract_pages(pages)
        mapped = map_classified_result(result) if version == "2" else map_result(result)
    else:
        service = build_medication_service()
        # 복약 파서의 5페이지 묶음 제한을 유지하며 최대 20페이지를 처리한다.
        parts = [
            service.extract_pages(pages[start : start + 5]) for start in range(0, len(pages), 5)
        ]
        from dataclasses import replace

        result = replace(
            parts[0], medications=tuple(item for part in parts for item in part.medications)
        )
        mapped = map_result(result)
    return {"pageCount": len(pages), "result": mapped}


def main() -> None:
    logging.disable(logging.CRITICAL)
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_RESULT_BYTES, MAX_RESULT_BYTES))
    from heapy_ocr.exceptions import ExternalServiceError, OcrError

    try:
        result = process(
            Path(sys.argv[1]), sys.argv[3], sys.argv[4], int(os.environ["MAX_UPLOAD_BYTES"])
        )
        encoded = encode(result)
        if len(encoded) > MAX_RESULT_BYTES - 4096:
            raise ContractError("RESULT_LIMIT")
    except ContractError as exc:
        encoded = encode({"errorCode": exc.code})
    except ExternalServiceError:
        encoded = encode({"errorCode": "EXTERNAL_SERVICE_FAILED"})
    except OcrError:
        encoded = encode({"errorCode": "EXTRACTION_FAILED"})
    except Exception:
        encoded = json.dumps({"errorCode": "PROCESSING_FAILED"}).encode()
    Path(sys.argv[2]).write_bytes(encoded)


if __name__ == "__main__":
    main()
