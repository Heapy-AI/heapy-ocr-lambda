"""실제 문서를 받지 않는 합성 OCR 모델 비교. 작성자: 김진우."""

import argparse
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from heapy_ocr.app_mapping import map_result
from heapy_ocr.gemini import GeminiCheckupParser, _request_payload
from heapy_ocr.general_checkup import GENERAL_INSTRUCTIONS
from heapy_ocr.service import HeapyOcrService


def synthetic(case):
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 23)
    draw.text((50, 40), "합성 일반건강검진 결과통보서 / 합성검증의원", font=font, fill="black")
    draw.text((50, 85), "검진일: 2031-04-12 (실제 인물 정보 없음)", font=font, fill="black")
    if case == "checkbox":
        rows = [
            ["목표질환", "검사항목", "실제 결과", "기관 판정 / 참고치"],
            ["빈혈", "혈색소 (g/dL)", "14.6", "■ 정상  □ 기타 / 11~18"],
            ["당뇨병", "공복혈당 (mg/dL)", "96", "□ 정상  ■ 재검요망 / 70~99"],
            ["지질", "총콜레스테롤", "비해당", "□ 정상  □ 이상 / 200 미만"],
            ["구분", "실시대상 여부", "검사명", "결과"],
            ["선택검사", "□ 해당 ■ 비해당", "골밀도검사", "□ 정상 □ 골다공증"],
            ["선택검사", "■ 해당 □ 비해당", "생활습관평가", "■ 절주 필요 □ 금연 필요"],
        ]
        expected = {
            ("HEMOGLOBIN", "14.6"),
            ("FASTING_GLUCOSE", "96"),
            ("LIFESTYLE_ASSESSMENT", "절주 필요"),
        }
        statuses = {"HEMOGLOBIN": "정상", "FASTING_GLUCOSE": "재검요망"}
    else:
        rows = [
            ["검사항목", "과거 결과", "금회 결과", "단위 / 참고치"],
            ["혈색소", "17.2", "14.6", "g/dL / 11~18"],
            ["공복혈당", "114", "96", "mg/dL / 70~99"],
            ["총콜레스테롤", "188", "", "mg/dL / 200 미만"],
            ["수축기혈압", "148", "128", "mmHg / 120 미만"],
            ["이완기혈압", "92", "78", "mmHg / 80 미만"],
        ]
        expected = {
            ("HEMOGLOBIN", "14.6"),
            ("FASTING_GLUCOSE", "96"),
            ("SYSTOLIC_BP", "128"),
            ("DIASTOLIC_BP", "78"),
        }
        statuses = {}
    xs = [50, 320, 620, 825, 1200]
    for r, row in enumerate(rows):
        y = 155 + r * 110
        for c, value in enumerate(row):
            draw.rectangle((xs[c], y, xs[c + 1], y + 110), outline="black", width=2)
            draw.text((xs[c] + 8, y + 25), value, font=font, fill="black")
    draw.text((50, 1080), "종합소견", font=font, fill="black")
    draw.text(
        (50, 1130), "관리가 필요합니다. 이 문장은 검사항목이 아닙니다.", font=font, fill="black"
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), expected, statuses


def score(payload, expected, statuses):
    extraction = GeminiCheckupParser._validate(payload)
    result = map_result(HeapyOcrService(None, None, 5_000_000)._build_result(extraction))
    actual = [(item["itemCode"], item["value"]) for item in result["items"]]
    pairs = set(actual)
    return {
        "expected": len(expected),
        "correct": len(expected & pairs),
        "missing": len(expected - pairs),
        "extra": len(pairs - expected),
        "duplicates": len(actual) - len(pairs),
        "status_expected": len(statuses),
        "status_correct": sum(
            any(item["itemCode"] == code and item["status"] == status for item in result["items"])
            for code, status in statuses.items()
        ),
        "date_correct": result["measuredAt"] == "2031-04-12",
        "provider_correct": result["providerName"] == "합성검증의원",
        "raw_count": len(payload.get("items", [])),
        "filtered_count": len(actual),
    }


def key_from_env():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key and Path(".env").exists():
        for line in Path(".env").read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                key = line.partition("=")[2].strip().strip('"').strip("'")
    if not key:
        raise SystemExit("테스트 키가 설정되지 않았습니다. 키를 채팅에 보내지 마세요.")
    return key


def main():
    parser = argparse.ArgumentParser(description="합성 표만 사용하는 모델 비교")
    parser.add_argument("--run", action="store_true")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--pro", action="store_true", help="2.5 Pro만 동일 조건으로 4회 비교")
    selection.add_argument("--pro31", action="store_true", help="3.1 Pro Preview만 4회 비교")
    args = parser.parse_args()
    output = Path("tmp/model-comparison-pro" if args.pro else "tmp/model-comparison")
    if args.pro31:
        output = Path("tmp/model-comparison-pro31")
    output.mkdir(parents=True, exist_ok=True)
    cases = {case: synthetic(case) for case in ("checkbox", "comparison")}
    for case, (data, _, _) in cases.items():
        (output / f"{case}.png").write_bytes(data)
    if not args.run:
        print("합성 이미지 준비 완료. --run 지정 시에만 외부 호출합니다.")
        return
    key = key_from_env()
    records = []
    for repeat in range(2):
        models = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]
        if args.pro:
            models = ["gemini-2.5-pro"]
        elif args.pro31:
            models = ["gemini-3.1-pro-preview"]
        if repeat:
            models.reverse()
        for case, (data, expected, statuses) in cases.items():
            for model in models:
                body = _request_payload(GENERAL_INSTRUCTIONS + " source_page는 1입니다.", (data,))
                body["generationConfig"]["maxOutputTokens"] = 8192
                request = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json", "x-goog-api-key": key},
                )
                record = {
                    "model": model,
                    "case": case,
                    "repeat": repeat + 1,
                    "image_sha256": hashlib.sha256(data).hexdigest(),
                }
                start = time.monotonic()
                try:
                    with urllib.request.urlopen(request, timeout=60) as response:
                        envelope = json.loads(response.read(2_000_000))
                    record["usage"] = envelope.get("usageMetadata", {})
                    record["model_version"] = envelope.get("modelVersion")
                    payload = json.loads(envelope["candidates"][0]["content"]["parts"][0]["text"])
                    record["score"] = score(payload, expected, statuses)
                    # 합성 응답만 저장하며 실제 문서를 입력하는 옵션은 제공하지 않는다.
                    (output / f"{model}-{case}-{repeat}.json").write_text(
                        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                    )
                except Exception as exc:
                    record["error_type"] = type(exc).__name__
                    record["http_status"] = (
                        exc.code if isinstance(exc, urllib.error.HTTPError) else None
                    )
                record["seconds"] = round(time.monotonic() - start, 2)
                records.append(record)
                (output / "metrics.json").write_text(
                    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(json.dumps(record, ensure_ascii=False), flush=True)
                if record.get("http_status") in (401, 403, 404, 429):
                    return


if __name__ == "__main__":
    main()
