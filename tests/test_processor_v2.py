"""앱 연결 전 실제 처리 진입점의 합성 검증. 작성자: 김진우."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from heapy_ocr import factory, files
from heapy_ocr.catalog import CATALOG_ROW_COUNT, MASTER_CHECKUP_ITEMS
from heapy_ocr.classified_parser import ClassifiedCheckupParser
from heapy_ocr.contract import ContractError
from heapy_ocr.matcher import CheckupItemMatcher
from heapy_ocr.models import RawCheckupItem
from heapy_ocr.processor import process
from heapy_ocr.service import HeapyOcrService


def extraction():
    return ClassifiedCheckupParser._validate(
        {
            "measured_at": "2031-04-12",
            "hospital_name": "합성 검진기관",
            "items": [
                {"raw_name": "청력(좌)", "raw_value": "정상"},
                {"raw_name": "흉부 X선", "raw_value": "합성 기관 판정"},
            ],
            "findings": [
                {
                    "exam_name": "위내시경",
                    "exam_type": "upper_gi_endoscopy",
                    "text": "합성 기관 소견",
                    "body_site": None,
                    "method": None,
                    "performed_at": None,
                }
            ],
            "overall_opinions": [],
            "review_required": [],
        }
    )


@pytest.mark.parametrize("version", [None, "1", "2"])
def test_processor_selects_schema_and_retains_findings(monkeypatch, version):
    monkeypatch.delenv("CHECKUP_SCHEMA_VERSION", raising=False)
    if version:
        monkeypatch.setenv("CHECKUP_SCHEMA_VERSION", version)
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"synthetic")
    monkeypatch.setattr(files, "convert", lambda *args: (b"synthetic",))
    service = Mock()
    service.extract_pages.return_value = HeapyOcrService(None, None, 1000)._build_result(
        extraction()
    )
    build = Mock(return_value=service)
    monkeypatch.setattr(factory, "build_service", build)
    result = process(Path("synthetic.pdf"), "pdf", "health_checkup", 1000)["result"]
    build.assert_called_once_with(classified=version != "1")
    if version == "1":
        assert set(result) == {"items", "measuredAt", "providerName"}
    else:
        assert result["schemaVersion"] == 2
        assert len(result["findings"]) == 1
        assert result["reviewRequired"] == []
        assert [item["itemCode"] for item in result["items"]] == [
            "HEARING_GENERAL_LEFT",
            "CHEST_XRAY",
        ]
        assert all(item["numericValue"] is None for item in result["items"])


def test_invalid_version_does_not_call_external_parser(monkeypatch):
    monkeypatch.setenv("CHECKUP_SCHEMA_VERSION", "3")
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"synthetic")
    monkeypatch.setattr(files, "convert", lambda *args: (b"synthetic",))
    build = Mock()
    monkeypatch.setattr(factory, "build_service", build)
    with pytest.raises(ContractError, match="INVALID_SCHEMA_VERSION"):
        process(Path("synthetic.pdf"), "pdf", "health_checkup", 1000)
    build.assert_not_called()


def test_catalog_general_hearing_does_not_accept_db_or_missing_side():
    assert len(MASTER_CHECKUP_ITEMS) == CATALOG_ROW_COUNT == 161
    matcher = CheckupItemMatcher(MASTER_CHECKUP_ITEMS)
    for name, value, unit in [
        ("청력(좌)", "15", "dB"),
        ("청력", "정상", None),
        ("청력 1000Hz(좌)", "정상", None),
    ]:
        assert matcher.match(RawCheckupItem(name, value, unit), 1).item_code is None
    assert (
        matcher.match(RawCheckupItem("청력 1000Hz(좌)", "15", "dB"), 1).item_code
        == "HEARING_1000HZ_LEFT"
    )
    assert matcher.match(RawCheckupItem("청력(우)", "정상"), 1).item_code == "HEARING_GENERAL_RIGHT"


def test_medication_processor_keeps_existing_contract(monkeypatch):
    from heapy_ocr.models import MedicationExtractionResult

    monkeypatch.setenv("CHECKUP_SCHEMA_VERSION", "2")
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"synthetic")
    monkeypatch.setattr(files, "convert", lambda *args: (b"synthetic",))
    service = Mock()
    service.extract_pages.return_value = MedicationExtractionResult(
        "synthetic", "MEDICATION", None, None, None, None, ()
    )
    monkeypatch.setattr(factory, "build_medication_service", lambda: service)
    checkup = Mock()
    monkeypatch.setattr(factory, "build_service", checkup)
    result = process(Path("synthetic.pdf"), "pdf", "medication", 1000)
    assert result == {"pageCount": 1, "result": {"items": []}}
    checkup.assert_not_called()
