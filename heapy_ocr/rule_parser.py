"""건강검진 OCR 원문을 규칙으로 구조화하는 파서.

작성자: 김진우
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date

from heapy_ocr.exceptions import OcrError
from heapy_ocr.general_checkup import excluded_label, general_lines, result_items
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
_RANGE_PATTERN = re.compile(r"[<>≤≥]?\s*-?\d+(?:\.\d+)?\s*(?:~|–|—|-)\s*[<>≤≥]?\s*-?\d+(?:\.\d+)?")
_NUMBER_PATTERN = re.compile(r"(?<![\w.])(?:[<>≤≥]=?\s*)?-?\d+(?:\.\d+)?(?![\w.])")
_UNIT_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:"
    r"mL/min/1\.73m2|kg/m2|mmHg|"
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
    "공복혈당": "FASTING_GLUCOSE",
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
    "혈청크레아티닌": "SERUM_CREATININE",
    "신사구체여과율": "EGFR",
    "신사구체여과율egfr": "EGFR",
    "에이에스티ast": "AST",
    "에이엘티alt": "ALT",
    "감마지티피γgtp": "GAMMA_GTP",
    "감마지티피gammagtp": "GAMMA_GTP",
    "고밀도콜레스테롤hdl": "HDL_CHOLESTEROL",
    "저밀도콜레스테롤ldl": "LDL_CHOLESTEROL",
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
    "height신장": "HEIGHT",
    "weight체중": "WEIGHT",
    "waist허리둘레": "WAIST_CIRCUMFERENCE",
    "혈압수축기systolicbp": "SYSTOLIC_BP",
    "혈압이완기diastolicbp": "DIASTOLIC_BP",
    "hb혈색소": "HEMOGLOBIN",
    "hemoglobin혈색소": "HEMOGLOBIN",
    "hct적혈구용적": "HEMATOCRIT",
    "wbc백혈구": "WBC_COUNT",
    "rbc적혈구": "RBC_COUNT",
    "platelet혈소판수": "PLATELET_COUNT",
    "astsgot혈청지오티": "AST",
    "altsgpt혈청지피티": "ALT",
    "creatinine크레아티닌": "SERUM_CREATININE",
    "tcholesterol총콜레스테롤": "TOTAL_CHOLESTEROL",
    "triglyceride중성지방": "TRIGLYCERIDES",
    "hdlcholesterol": "HDL_CHOLESTEROL",
    "ldlcholesterol": "LDL_CHOLESTEROL",
    "uprotein요단백": "URINE_PROTEIN",
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
        self._terms = tuple(sorted(terms, key=lambda term: len(term.normalized), reverse=True))

    def parse(self, lines: tuple[str, ...]) -> CheckupExtraction:
        lines = general_lines(lines)
        measured_at = _extract_date(lines)
        hospital_name = _extract_hospital(lines)
        items: list[RawCheckupItem] = []
        pending_term: _ItemTerm | None = None
        source_page = None
        table_columns = None
        comparison_layout = False
        excluded_section = False

        for raw_line in lines:
            line = _clean_line(raw_line)
            marker = re.fullmatch(r"--- (\d+)페이지 ---", line)
            if marker:
                source_page = int(marker.group(1))
                pending_term = None
                table_columns = None
                comparison_layout = False
                excluded_section = False
                continue
            if not line:
                pending_term = None
                continue
            section = _section_boundary(line)
            if section is not None:
                excluded_section = section
                table_columns = None
                pending_term = None
                continue
            if excluded_section:
                continue
            if re.search(r"과거\s*(?:결과|검사)|이전\s*결과|previous\s*result", line, re.I):
                comparison_layout = True
                pending_term = None
            if "|" in line:
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                header = _table_columns(cells)
                if header is not None:
                    table_columns = header
                elif table_columns:
                    parsed = _table_item(cells, table_columns, source_page)
                    if parsed:
                        items.extend(result_items(parsed))
                pending_term = None
                continue
            if comparison_layout:
                # 열 좌표가 사라진 비교표에서는 첫 숫자를 현재 결과로 추정하지 않는다.
                pending_term = None
                continue
            table_columns = None
            if (
                excluded_label(line)
                or re.search(r"참고치|정상범위|목표\s*(?:값|상태)|필요합니다", line)
                or re.match(
                    r"^(?:과거병력|과거력|약물치료|예방접종|흡연|음주|신체활동|근력운동)(?:\s|[:：])",
                    line,
                )
            ):
                pending_term = None
                continue
            if any(marker in line for marker in ("□", "■", "☑", "☐", "▣")):
                # 텍스트 fallback으로 체크 위치·표 열을 보장할 수 없는 행은 추정하지 않는다.
                pending_term = None
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
            items.extend(replace(item, source_page=source_page) for item in compound_items)
            if compound_items:
                pending_term = None
                continue

            occurrences = self._find_items(line)
            if occurrences:
                parsed_count = 0
                for index, (start, _, term) in enumerate(occurrences):
                    end = occurrences[index + 1][0] if index + 1 < len(occurrences) else len(line)
                    parsed = self._parse_item_line(line[start:end], term)
                    if parsed is not None:
                        items.append(replace(parsed, source_page=source_page))
                        parsed_count += 1
                term = occurrences[-1][2]
                pending_term = (
                    term if parsed_count == 0 and _normalize(line) == term.normalized else None
                )
                continue

            if pending_term is not None:
                parsed = self._parse_item_line(line, pending_term, name_in_line=False)
                if parsed is not None:
                    items.append(replace(parsed, source_page=source_page))
                pending_term = None

        if not items:
            raise OcrError(
                "OCR 원문에서 저장 가능한 건강검진 항목을 찾지 못했습니다. "
                "검사명과 결과값이 명확하게 보이는 파일로 다시 요청해 주세요."
            )
        return CheckupExtraction(
            measured_at=measured_at,
            hospital_name=hospital_name,
            items=tuple(filtered for item in items for filtered in result_items(item)),
        )

    def _find_items(self, line: str) -> tuple[tuple[int, int, _ItemTerm], ...]:
        candidates: list[tuple[int, int, _ItemTerm]] = []
        for term in self._terms:
            tokens = re.findall(r"[A-Za-z]+|\d+|[가-힣]+", term.text)
            if not tokens:
                continue
            flexible = r"[^0-9A-Za-z가-힣]*".join(re.escape(token) for token in tokens)
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
                start < saved_end and end > saved_start for saved_start, saved_end, _ in selected
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
            raw_unit=unit,
            printed_status=status,
        )


def _extract_date(lines: tuple[str, ...]) -> str | None:
    dates = set()
    for line in lines:
        if not re.search(r"검진\s*(?:일자|일|날짜)|검사\s*(?:일자|일)|수검일", line):
            continue
        if re.search(r"과거|이전|발행|출력|판정", line):
            continue
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
            dates.add(measured_at.isoformat())
    return next(iter(dates)) if len(dates) == 1 else None


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
    if "혈압" not in line or not re.search(r"mm\s*Hg", line, re.IGNORECASE):
        return ()
    match = re.search(r"(?<!\d)(\d{2,3})\s*/\s*(\d{2,3})(?!\d)", line)
    if not match:
        return ()
    status_match = _STATUS_PATTERN.search(line)
    status = _compact(status_match.group(0)) if status_match else None
    item = RawCheckupItem(line, f"{match.group(1)}/{match.group(2)}", "mmHg", status)
    split = result_items(item)
    return split if len(split) == 2 else ()


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
        RawCheckupItem("신장", match.group(1), "cm" if re.search(r"키\s*\(?cm", line) else None),
        RawCheckupItem(
            "체중", match.group(2), "kg" if re.search(r"몸무게\s*\(?kg", line) else None
        ),
    )


def _extract_left_and_right(
    line: str,
    label: str,
    left_code: str,
    right_code: str,
) -> tuple[RawCheckupItem, ...]:
    if label not in line:
        return ()
    if label == "청력" and "1000" not in line:
        qualitative = re.search(r"청력.*?(정상|비정상)\s*/\s*(정상|비정상)", line)
        if qualitative:
            return (
                RawCheckupItem("청력(좌)", qualitative.group(1)),
                RawCheckupItem("청력(우)", qualitative.group(2)),
            )
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


def _table_columns(cells: list[str]) -> dict[str, int] | None:
    """명시적인 구분자가 있는 합성·텍스트 표에서만 열을 연결한다. 작성자: 김진우."""
    labels = {
        "name": {"검사명", "검사항목"},
        "value": {"결과", "검사결과", "실제결과"},
        "unit": {"단위"},
        "status": {"기관판정", "판정"},
    }
    normalized = [_normalize(cell) for cell in cells]
    if not any(cell in labels["name"] for cell in normalized):
        return None
    columns = {}
    for key, names in labels.items():
        matches = [i for i, cell in enumerate(normalized) if cell in names]
        if len(matches) > 1:
            return {}
        if matches:
            columns[key] = matches[0]
    current = [i for i, cell in enumerate(normalized) if cell in {
        "금회결과", "금회검사결과", "현재결과", "이번결과", "currentresult",
    }]
    comparison = any(re.search(r"과거|이전|previous", cell) for cell in normalized)
    if len(current) == 1:
        columns["value"] = current[0]
    elif len(current) > 1 or comparison:
        return {}
    return columns if "name" in columns and "value" in columns else {}


def _section_boundary(line: str) -> bool | None:
    """명시적인 영역 제목만 인식한다. 기관별 전체 페이지를 일괄 제외하지 않는다. 작성자: 김진우."""
    label = _normalize(line)
    if label in {
        "종합소견", "건강검진종합소견", "주요결과", "최근5년간주요검사항목",
        "내시경검사", "위내시경검사", "조직검사", "초음파검사", "ct검사", "mri검사",
    }:
        return True
    if label in {
        "신체계측검사", "신체계측및기초검사", "기초및신체계측", "혈액검사",
        "혈액질환검사", "간기능검사", "신장기능검사", "당뇨병검사", "소변검사",
        "요화학검사", "흉부엑스선검사", "심혈관및이상지질혈증검사",
        "일반건강검진결과통보서",
    }:
        return False
    return None


def _table_item(cells, columns, source_page):
    if max(columns.values()) >= len(cells):
        return None
    name, value = cells[columns["name"]], cells[columns["value"]]
    if not name or not value or any(marker in " ".join(cells) for marker in ("□", "■", "☑")):
        return None
    unit = cells[columns["unit"]] or None if "unit" in columns else None
    status = cells[columns["status"]] or None if "status" in columns else None
    return RawCheckupItem(name, value, unit, status, source_page)
