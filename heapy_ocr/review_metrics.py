"""저장 제외 후보의 원문 없는 개선 지표. 작성자: 김진우."""

import json
import re
from uuid import UUID

from heapy_ocr.catalog import CATALOG_SHA256

REASONS = ("uncertain_classification", "unmatched_item", "invalid_extraction")


def emit_review_metrics(logger, job_id, envelope):
    """완료된 OCR 후보만 집계한다. 확정·제외 실행 또는 정확도 판정이 아니다."""
    try:
        if str(UUID(job_id)) != job_id:
            return
        result = envelope.get("result")
        if not isinstance(result, dict) or result.get("schemaVersion") != 2:
            return
        arrays = [
            result.get(key) for key in ("items", "findings", "overallOpinions", "reviewRequired")
        ]
        if any(not isinstance(values, list) for values in arrays):
            return
        if any(
            len(values) > limit for values, limit in zip(arrays, (200, 50, 20, 200), strict=True)
        ):
            return
        reasons = dict.fromkeys(REASONS, 0)
        patterns = dict.fromkeys(("procedure_label", "unit_in_pair", "other"), 0)
        for item in arrays[3]:
            if not isinstance(item, dict) or item.get("reason") not in REASONS:
                return
            text = item.get("text")
            if not isinstance(text, str) or len(text) > 2000:
                return
            reasons[item["reason"]] += 1
            # 작성자: 김진우 — 원문을 로그로 옮기지 않고 코드가 정의한 형식 특징만 집계한다.
            if re.search(r"내시경|조직\s*검사|endoscop|biopsy", text, re.I):
                pattern = "procedure_label"
            elif re.search(r"\d\s*mmHg\s*/\s*\d", text, re.I):
                pattern = "unit_in_pair"
            else:
                pattern = "other"
            patterns[pattern] += 1
        pages = envelope.get("pageCount")
        if type(pages) is not int or not 1 <= pages <= 20:
            return
        event = {
            "metricVersion": 1,
            "schemaVersion": 2,
            "catalogSha256": CATALOG_SHA256,
            "pageCount": pages,
            "itemCount": len(arrays[0]),
            "findingCount": len(arrays[1]),
            "overallOpinionCount": len(arrays[2]),
            "excludedCandidateCount": len(arrays[3]),
            "reasonCounts": reasons,
            "patternCounts": patterns,
        }
        logger.info(
            "OCR_REVIEW_CANDIDATES jobId=%s metrics=%s",
            job_id,
            json.dumps(event, sort_keys=True, separators=(",", ":")),
        )
    except Exception:
        # 작성자: 김진우 — 지표 장애가 완료 결과·정리에 영향을 주지 않는다.
        return
