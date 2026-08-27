"""Gemini 구조화 결과 검증 테스트.

작성자: 김진우
"""

from heapy_ocr.gemini import GeminiCheckupParser


def test_구조화_결과에서_유효한_검사항목만_선택한다() -> None:
    result = GeminiCheckupParser._validate(
        {
            "measured_at": "2026-07-15",
            "hospital_name": "HEAPY 검진센터",
            "items": [
                {
                    "raw_name": "공복혈당",
                    "raw_value": "108",
                    "raw_unit": "mg/dL",
                    "printed_status": "정상B",
                },
                {
                    "raw_name": "",
                    "raw_value": "120",
                    "raw_unit": None,
                    "printed_status": None,
                },
            ],
        }
    )

    assert result.measured_at == "2026-07-15"
    assert result.hospital_name == "HEAPY 검진센터"
    assert len(result.items) == 1
