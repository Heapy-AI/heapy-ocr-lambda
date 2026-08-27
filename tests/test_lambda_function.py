"""Lambda HTTP 계약 테스트.

작성자: 김진우
"""

import base64
import json

import lambda_function
from heapy_ocr.models import ExtractionResult, ParsedCheckupItem


class FakeService:
    """외부 서비스를 호출하지 않는 애플리케이션 서비스 대역."""

    def extract(self, image_bytes, access_token):
        assert image_bytes.startswith(b"\xff\xd8\xff")
        assert access_token == "user-token"
        return ExtractionResult(
            request_id="request-id",
            ocr_type="HEALTH_CHECKUP",
            measured_at="2026-07-15",
            hospital_name="HEAPY 검진센터",
            items=(
                ParsedCheckupItem(
                    raw_name="공복혈당",
                    item_code="FASTING_GLUCOSE",
                    item_name="공복혈당",
                    raw_value="108",
                    value="108",
                    unit="mg/dL",
                    printed_status="정상B",
                    confidence=0.97,
                    needs_review=False,
                ),
            ),
        )

    def confirm_and_save(self, access_token, measured_at, items):
        assert access_token == "user-token"
        assert measured_at == "2026-07-15"
        assert items[0].item_code == "FASTING_GLUCOSE"
        return "record-id"


def _event(payload):
    return {
        "headers": {
            "x-internal-secret-key": "internal-secret",
            "authorization": "Bearer user-token",
        },
        "body": json.dumps(payload),
    }


def setup_function() -> None:
    lambda_function._service = FakeService()


def test_extract_요청은_확인용_초안을_반환한다(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SECRET_KEY", "internal-secret")
    image = base64.b64encode(b"\xff\xd8\xfftest-image").decode("ascii")

    response = lambda_function.lambda_handler(
        _event(
            {
                "ocr_type": "HEALTH_CHECKUP",
                "operation": "EXTRACT",
                "image_base64": image,
            }
        ),
        None,
    )

    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["result"]["request_id"] == "request-id"


def test_confirm_and_save는_명시적_확인을_요구한다(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SECRET_KEY", "internal-secret")

    response = lambda_function.lambda_handler(
        _event(
            {
                "ocr_type": "HEALTH_CHECKUP",
                "operation": "CONFIRM_AND_SAVE",
                "confirmed": False,
                "measured_at": "2026-07-15",
                "items": [],
            }
        ),
        None,
    )

    assert response["statusCode"] == 400


def test_confirm_and_save는_record_id를_반환한다(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_SECRET_KEY", "internal-secret")

    response = lambda_function.lambda_handler(
        _event(
            {
                "ocr_type": "HEALTH_CHECKUP",
                "operation": "CONFIRM_AND_SAVE",
                "confirmed": True,
                "measured_at": "2026-07-15",
                "items": [
                    {
                        "raw_name": "공복혈당",
                        "item_code": "FASTING_GLUCOSE",
                        "item_name": "공복혈당",
                        "raw_value": "108",
                        "value": "108",
                        "unit": "mg/dL",
                        "printed_status": "정상B",
                    }
                ],
            }
        ),
        None,
    )

    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["result"]["record_id"] == "record-id"
