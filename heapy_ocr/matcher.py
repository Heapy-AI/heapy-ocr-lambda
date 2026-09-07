"""OCR 검사명을 HEAPY 건강검진 마스터 코드에 연결한다.

작성자: 김진우
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from heapy_ocr.models import MasterCheckupItem, ParsedCheckupItem, RawCheckupItem
from heapy_ocr.rule_parser import ITEM_CODE_ALIASES

_ALIASES = {
    "혈압최고": "수축기혈압",
    "최고혈압": "수축기혈압",
    "혈압최저": "이완기혈압",
    "최저혈압": "이완기혈압",
    "공복시혈당": "공복혈당",
    "혈당식전": "공복혈당",
    "감마지티피": "감마지티피γgtp",
    "sgot": "에이에스티ast",
    "sgpt": "에이엘티alt",
}


class CheckupItemMatcher:
    """마스터 명칭과 OCR 명칭의 보수적 유사도 매칭."""

    def __init__(self, catalog: tuple[MasterCheckupItem, ...]) -> None:
        self.catalog = catalog
        self._normalized = {
            item.item_code: _normalize(item.item_name) for item in catalog
        }

    def match(
        self,
        raw_item: RawCheckupItem,
        ocr_confidence: float,
    ) -> ParsedCheckupItem:
        query = _normalize(raw_item.raw_name)
        if "청력" in query and "1000" not in query:
            # 일반 청력 판정을 특정 주파수 검사 코드로 추정하지 않는다.
            return _matched_item(raw_item, None, ocr_confidence, 0.0)
        alias_code = ITEM_CODE_ALIASES.get(query)
        if alias_code is not None:
            alias_match = next(
                (item for item in self.catalog if item.item_code == alias_code),
                None,
            )
            if alias_match is not None:
                return _matched_item(raw_item, alias_match, ocr_confidence, 1.0)
        query = _ALIASES.get(query, query)
        best_item: MasterCheckupItem | None = None
        best_score = 0.0
        for item in self.catalog:
            candidate = self._normalized[item.item_code]
            score = self._score(query, candidate, item.item_code)
            if score > best_score:
                best_score = score
                best_item = item

        matched = best_item if best_score >= 0.66 else None
        return _matched_item(raw_item, matched, ocr_confidence, best_score)

    @staticmethod
    def _score(query: str, candidate: str, item_code: str) -> float:
        if not query or not candidate:
            return 0.0
        normalized_code = _normalize(item_code)
        if query == candidate or query == normalized_code:
            return 1.0
        if len(query) >= 3 and (query in candidate or candidate in query):
            return 0.9
        query_tokens = set(re.findall(r"[a-z]+|\d+|[가-힣]+", query))
        candidate_tokens = set(re.findall(r"[a-z]+|\d+|[가-힣]+", candidate))
        token_score = (
            len(query_tokens & candidate_tokens) / len(query_tokens | candidate_tokens)
            if query_tokens and candidate_tokens
            else 0.0
        )
        sequence_score = SequenceMatcher(None, query, candidate).ratio()
        return max(sequence_score, token_score)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("γ", "gamma")
    return re.sub(r"[^0-9a-z가-힣]", "", normalized)


def _normalize_value(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _matched_item(
    raw_item: RawCheckupItem,
    matched: MasterCheckupItem | None,
    ocr_confidence: float,
    match_score: float,
) -> ParsedCheckupItem:
    confidence = round(min(ocr_confidence, match_score), 4)
    unit = (
        matched.standard_unit
        if matched is not None and matched.standard_unit
        else raw_item.raw_unit
    )
    needs_review = matched is None or confidence < 0.82
    return ParsedCheckupItem(
        raw_name=raw_item.raw_name,
        item_code=matched.item_code if matched else None,
        item_name=matched.item_name if matched else None,
        raw_value=raw_item.raw_value,
        value=_normalize_value(raw_item.raw_value),
        raw_unit=raw_item.raw_unit,
        unit=unit,
        printed_status=raw_item.printed_status,
        source_page=raw_item.source_page,
        detail_data=raw_item.detail_data,
        confidence=confidence,
        needs_review=needs_review,
    )
