"""건강검진 OCR 원문을 규칙으로 구조화하는 파서.

작성자: 김진우
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from heapy_ocr.exceptions import OcrError
from heapy_ocr.models import CheckupSummary, MasterCheckupItem, RawCheckupItem

_DATE_PATTERNS = (
    re.compile(r"(?P<year>20\d{2})[.\-/년]\s*(?P<month>\d{1,2})[.\-/월]\s*(?P<day>\d{1,2})일?"),
    re.compile(r"(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})"),
)
_HOSPITAL_PATTERN = re.compile(r"(?:병원|의원|의료원|검진센터|건강검진센터|보건소)")
_STATUS_PATTERN = re.compile(
    r"정상\s*[AB]?|경계|주의|질환\s*의심|유질환자|이상\s*소견|재검\s*요망|"
    r"추적\s*관찰|양호|관리\s*필요",
    re.IGNORECASE,
)
_QUALITATIVE_VALUE_PATTERN = re.compile(
    r"(?<![가-힣])(음성|양성|미실시|미검|비반응|반응|trace|negative|positive)(?![가-힣])",
    re.IGNORECASE,
)
_RANGE_PATTERN = re.compile(
    r"[<>≤≥]?\s*-?\d+(?:\.\d+)?\s*(?:~|–|—|-)\s*[<>≤≥]?\s*-?\d+(?:\.\d+)?"
)
_NUMBER_PATTERN = re.compile(r"(?<![\w.])(?:[<>≤≥]=?\s*)?-?\d+(?:\.\d+)?(?![\w.])")
_UNIT_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:"
    r"(?:mg|g|ng|pg|ug|μg|mmol|mIU|uIU|IU|pmol|mL|mm|cm|kg|dB|fL|L|U)"
    r"(?:\s*/\s*(?:dL|mL|L|g|min|hr|HPF|LPF|1\.73m2))?"
    r"|%|kg/m2|10\^\d+/uL|/min|/HPF|/LPF)(?![A-Za-z])",
    re.IGNORECASE,
)
# 국가검진 결과지와 일반 검진기관에서 자주 사용하는 표기입니다.
ITEM_CODE_ALIASES = {
    "키": "HEIGHT",
    "신장": "HEIGHT",
    "몸무게": "WEIGHT",
    "체중": "WEIGHT",
    "체질량지수": "BMI",
    "bmi": "BMI",
    "허리둘레": "WAIST_CIRCUMFERENCE",
    "혈압최고": "SYSTOLIC_BP",
    "최고혈압": "SYSTOLIC_BP",
    "수축기": "SYSTOLIC_BP",
    "혈압최저": "DIASTOLIC_BP",
    "최저혈압": "DIASTOLIC_BP",
    "이완기": "DIASTOLIC_BP",
    "공복시혈당": "FASTING_GLUCOSE",
    "식전혈당": "FASTING_GLUCOSE",
    "혈당식전": "FASTING_GLUCOSE",
    "혈당": "FASTING_GLUCOSE",
    "sgot": "AST",
    "ast": "AST",
    "sgpt": "ALT",
    "alt": "ALT",
    "감마gtp": "GAMMA_GTP",
    "감마지티피": "GAMMA_GTP",
    "ggt": "GAMMA_GTP",
    "γgtp": "GAMMA_GTP",
    "rgtp": "GAMMA_GTP",
    "hba1c": "HBA1C",
    "당화혈색소": "HBA1C",
    "총콜레스테롤": "TOTAL_CHOLESTEROL",
    "고밀도콜레스테롤": "HDL_CHOLESTEROL",
    "hdl콜레스테롤": "HDL_CHOLESTEROL",
    "저밀도콜레스트롤": "LDL_CHOLESTEROL",
    "저밀도콜레스테롤": "LDL_CHOLESTEROL",
    "ldl콜레스테롤": "LDL_CHOLESTEROL",
    "중성지방": "TRIGLYCERIDES",
    "크레아티닌": "SERUM_CREATININE",
    "egfr": "EGFR",
    "혈색소": "HEMOGLOBIN",
    "헤모글로빈": "HEMOGLOBIN",
    "백혈구": "WBC_COUNT",
    "wbc": "WBC_COUNT",
    "철": "IRON",
    "iron": "IRON",
    "25ohvitamindtotal": "VITAMIN_D_25_OH",
    "비타민25ohvitamindtotal": "VITAMIN_D_25_OH",
    "요단백": "URINE_PROTEIN",
    "요당": "URINE_GLUCOSE",
    "요잠혈": "URINE_OCCULT_BLOOD",
    "흉부촬영": "CHEST_XRAY_PA",
    "흉부방사선촬영": "CHEST_XRAY_PA",
}


@dataclass(frozen=True)
class CheckupExtraction:
    """파서가 반환한 건강검진 문서 구조."""

    measured_at: str | None
    hospital_name: str | None
    items: tuple[RawCheckupItem, ...]
    parser_mode: str = "rule"
    parser_warnings: tuple[str, ...] = ()
    document_type: str = "UNKNOWN"
    summary: CheckupSummary = field(default_factory=CheckupSummary)


@dataclass(frozen=True)
class _ItemTerm:
    text: str
    normalized: str
    item_code: str


class RuleBasedCheckupParser:
    """내부 검사 마스터와 보수적인 정규식으로 OCR 줄을 파싱한다."""

    def __init__(self, catalog: tuple[MasterCheckupItem, ...]) -> None:
        self.catalog = catalog
        self._catalog_by_code = {item.item_code: item for item in catalog}
        terms = [
            _ItemTerm(item.item_name, _normalize(item.item_name), item.item_code)
            for item in catalog
        ]
        terms.extend(
            _ItemTerm(alias, _normalize(alias), item_code)
            for alias, item_code in ITEM_CODE_ALIASES.items()
            if item_code in self._catalog_by_code
        )
        self._terms = tuple(
            sorted(terms, key=lambda term: len(term.normalized), reverse=True)
        )

    def parse(self, lines: tuple[str, ...]) -> CheckupExtraction:
        measured_at = _extract_date(lines)
        hospital_name = _extract_hospital(lines)
        items: list[RawCheckupItem] = []
        pending_term: _ItemTerm | None = None

        for raw_line in lines:
            line = _clean_line(raw_line)
            if not line or line.startswith("--- "):
                continue

            compound_items = (
                *_extract_height_and_weight(line),
                *_extract_combined_blood_pressure(line),
                *_extract_left_and_right(
                    line,
                    "시력",
                    "VISUAL_ACUITY_LEFT",
                    "VISUAL_ACUITY_RIGHT",
                ),
                *_extract_left_and_right(
                    line,
                    "청력",
                    "HEARING_1000HZ_LEFT",
                    "HEARING_1000HZ_RIGHT",
                ),
            )
            items.extend(compound_items)

            occurrences = self._find_items(line)
            if occurrences:
                parsed_count = 0
                for index, (start, _, term) in enumerate(occurrences):
                    end = occurrences[index + 1][0] if index + 1 < len(occurrences) else len(line)
                    parsed = self._parse_item_line(line[start:end], term)
                    if parsed is not None:
                        items.append(parsed)
                        parsed_count += 1
                pending_term = occurrences[-1][2] if parsed_count == 0 else None
                continue

            if pending_term is not None:
                parsed = self._parse_item_line(line, pending_term, name_in_line=False)
                if parsed is not None:
                    items.append(parsed)
                pending_term = None

        if not items:
            raise OcrError(
                "OCR 원문에서 저장 가능한 건강검진 항목을 찾지 못했습니다. "
                "원문 OCR 탭에서 검사명과 결과값이 같은 줄에 인식됐는지 확인해 주세요."
            )
        return CheckupExtraction(
            measured_at=measured_at,
            hospital_name=hospital_name,
            items=tuple(items),
        )

    def _find_items(self, line: str) -> tuple[tuple[int, int, _ItemTerm], ...]:
        candidates: list[tuple[int, int, _ItemTerm]] = []
        for term in self._terms:
            tokens = re.findall(r"[A-Za-z]+|\d+|[가-힣]+", term.text)
            if not tokens:
                continue
            flexible = r"[^0-9A-Za-z가-힣]*".join(
                re.escape(token) for token in tokens
            )
            pattern = re.compile(
                rf"(?<![0-9A-Za-z가-힣]){flexible}(?![0-9A-Za-z가-힣])",
                re.IGNORECASE,
            )
            for match in pattern.finditer(line):
                candidates.append((match.start(), match.end(), term))

        selected: list[tuple[int, int, _ItemTerm]] = []
        selected_codes: set[str] = set()
        for candidate in sorted(
            candidates,
            key=lambda value: (value[0], -(value[1] - value[0])),
        ):
            start, end, term = candidate
            if term.item_code in selected_codes:
                continue
            overlaps = any(
                start < saved_end and end > saved_start
                for saved_start, saved_end, _ in selected
            )
            if overlaps:
                continue
            selected.append(candidate)
            selected_codes.add(term.item_code)
        return tuple(sorted(selected, key=lambda value: value[0]))

    def _parse_item_line(
        self,
        line: str,
        term: _ItemTerm,
        *,
        name_in_line: bool = True,
    ) -> RawCheckupItem | None:
        remainder = _remove_term(line, term.text) if name_in_line else line
        if "비해당" in remainder:
            return None
        status_match = _STATUS_PATTERN.search(remainder)
        status = _compact(status_match.group(0)) if status_match else None
        if status_match:
            remainder = remainder[: status_match.start()] + remainder[status_match.end() :]

        unit_match = _UNIT_PATTERN.search(remainder)
        unit = unit_match.group(0).replace(" ", "") if unit_match else None
        if unit_match:
            remainder = remainder[: unit_match.start()] + remainder[unit_match.end() :]

        qualitative = _QUALITATIVE_VALUE_PATTERN.search(remainder)
        if qualitative:
            value = qualitative.group(0).strip()
        else:
            without_dates = remainder
            for date_pattern in _DATE_PATTERNS:
                without_dates = date_pattern.sub(" ", without_dates)
            without_ranges = _RANGE_PATTERN.sub(" ", without_dates)
            value = _first_result_number(without_ranges)
        master = self._catalog_by_code[term.item_code]
        if not value and status and master.standard_unit is None:
            value = status
        if not value:
            return None

        return RawCheckupItem(
            raw_name=term.text,
            raw_value=value,
            raw_unit=unit or master.standard_unit,
            printed_status=status,
        )


def _extract_date(lines: tuple[str, ...]) -> str | None:
    for line in lines:
        for pattern in _DATE_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            try:
                measured_at = date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            except ValueError:
                continue
            return measured_at.isoformat()
    return None


def _extract_hospital(lines: tuple[str, ...]) -> str | None:
    for raw_line in lines:
        line = _clean_line(raw_line)
        if not _HOSPITAL_PATTERN.search(line):
            continue
        candidate = re.sub(r"^(?:검진기관|검사기관|의료기관|기관명)\s*[:：]?\s*", "", line)
        if 2 <= len(candidate) <= 80:
            return candidate
    return None


def _extract_combined_blood_pressure(line: str) -> tuple[RawCheckupItem, ...]:
    if "혈압" not in line:
        return ()
    match = re.search(r"(?<!\d)(\d{2,3})\s*/\s*(\d{2,3})(?!\d)", line)
    if not match:
        return ()
    status_match = _STATUS_PATTERN.search(line)
    status = _compact(status_match.group(0)) if status_match else None
    return (
        RawCheckupItem("수축기혈압", match.group(1), "mmHg", status),
        RawCheckupItem("이완기혈압", match.group(2), "mmHg", status),
    )


def _extract_height_and_weight(line: str) -> tuple[RawCheckupItem, ...]:
    if "키" not in line or "몸무게" not in line:
        return ()
    match = re.search(
        r"키.*?몸무게.*?(\d{2,3}(?:\.\d+)?)\s*/\s*(\d{2,3}(?:\.\d+)?)",
        line,
    )
    if not match:
        return ()
    return (
        RawCheckupItem("신장", match.group(1), "cm"),
        RawCheckupItem("체중", match.group(2), "kg"),
    )


def _extract_left_and_right(
    line: str,
    label: str,
    left_code: str,
    right_code: str,
) -> tuple[RawCheckupItem, ...]:
    if label not in line:
        return ()
    match = re.search(
        rf"{label}[^\d]{{0,20}}(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)",
        line,
    )
    if not match:
        return ()
    names = {
        "VISUAL_ACUITY_LEFT": "시력(좌)",
        "VISUAL_ACUITY_RIGHT": "시력(우)",
        "HEARING_1000HZ_LEFT": "청력 1000Hz(좌)",
        "HEARING_1000HZ_RIGHT": "청력 1000Hz(우)",
    }
    return (
        RawCheckupItem(names[left_code], match.group(1)),
        RawCheckupItem(names[right_code], match.group(2)),
    )


def _clean_line(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("γ", "gamma")
    return re.sub(r"[^0-9a-z가-힣]", "", normalized)


def _remove_term(line: str, term: str) -> str:
    direct = re.sub(re.escape(term), " ", line, count=1, flags=re.IGNORECASE)
    if direct != line:
        return direct
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", term)
    if not tokens:
        return line
    flexible = r"[^0-9A-Za-z가-힣]*".join(re.escape(token) for token in tokens)
    return re.sub(flexible, " ", line, count=1, flags=re.IGNORECASE)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _first_result_number(value: str) -> str | None:
    """참고 기준 숫자를 제외하고 첫 번째 실제 결과 수치를 반환한다."""

    for match in _NUMBER_PATTERN.finditer(value):
        suffix = value[match.end() :]
        if re.match(r"\s*(?:미만|이하|이상|초과)", suffix):
            continue
        return match.group(0).replace(" ", "")
    return None
