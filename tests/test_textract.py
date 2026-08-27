"""Textract 응답 정리 테스트.

작성자: 김진우
"""

from heapy_ocr.textract import TextractAnalyzer


class FakeTextractClient:
    """고정 응답을 제공하는 Textract 테스트 대역."""

    def analyze_document(self, **kwargs):
        assert kwargs["FeatureTypes"] == ["TABLES", "FORMS"]
        return {
            "Blocks": [
                {"BlockType": "LINE", "Text": "공복혈당 108 mg/dL", "Confidence": 98.0},
                {"BlockType": "WORD", "Text": "공복혈당", "Confidence": 99.0},
                {"BlockType": "LINE", "Text": "AST 31 U/L", "Confidence": 96.0},
            ]
        }


def test_라인과_평균신뢰도를_추출한다() -> None:
    document = TextractAnalyzer(FakeTextractClient()).analyze(b"image")

    assert document.lines == ("공복혈당 108 mg/dL", "AST 31 U/L")
    assert document.average_confidence == 0.97
