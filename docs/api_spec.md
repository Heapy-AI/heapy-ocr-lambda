# HEAPY OCR API 명세

- 작성자: 김진우
- 전송 방식: Lambda Function URL `POST`

## 공통 헤더

```http
Content-Type: application/json
x-internal-secret-key: {INTERNAL_SECRET_KEY}
Authorization: Bearer {SUPABASE_USER_ACCESS_TOKEN}
```

## 건강검진 결과 추출

### 요청

```json
{
  "operation": "EXTRACT",
  "ocr_type": "HEALTH_CHECKUP",
  "image_base64": "/9j/4AAQSkZJRg..."
}
```

### 성공 응답

```json
{
  "is_success": true,
  "result": {
    "request_id": "UUID",
    "ocr_type": "HEALTH_CHECKUP",
    "measured_at": "2026-07-15",
    "hospital_name": "HEAPY 검진센터",
    "items": [
      {
        "raw_name": "공복 혈당",
        "item_code": "FASTING_GLUCOSE",
        "item_name": "공복혈당",
        "raw_value": "108",
        "value": "108",
        "unit": "mg/dL",
        "printed_status": "정상B",
        "confidence": 0.94,
        "needs_review": false
      }
    ],
    "warnings": []
  }
}
```

## 확인된 결과 저장

`EXTRACT` 응답을 화면에 표시하고 사용자가 수정·확인한 뒤 호출합니다.

### 요청

```json
{
  "operation": "CONFIRM_AND_SAVE",
  "ocr_type": "HEALTH_CHECKUP",
  "confirmed": true,
  "measured_at": "2026-07-15",
  "items": [
    {
      "raw_name": "공복 혈당",
      "item_code": "FASTING_GLUCOSE",
      "item_name": "공복혈당",
      "raw_value": "108",
      "value": "108",
      "unit": "mg/dL",
      "printed_status": "정상B"
    }
  ]
}
```

### 성공 응답

```json
{
  "is_success": true,
  "result": {
    "record_id": "건강검진 회차 UUID",
    "measured_at": "2026-07-15",
    "saved_item_count": 1
  }
}
```

## 오류

| 상태 | 조건 |
|---|---|
| `400` | JSON, Base64, 날짜, 항목 코드, 확인 상태 오류 |
| `401` | 내부 시크릿 또는 사용자 JWT 오류 |
| `502` | Supabase가 요청을 거부하거나 저장에 실패 |
| `503` | 환경변수, Textract, Gemini, Supabase 연결 실패 |
| `500` | 예상하지 못한 내부 오류 |
