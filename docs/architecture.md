# HEAPY OCR 시스템 아키텍처

- 작성자: 김진우

## 책임 경계

HEAPY OCR Lambda는 건강검진 결과지의 텍스트 추출, 구조화, 표준 검사항목 매핑과
확인된 결과 저장만 담당합니다. 건강 수치 해석, 진단, 판정 재계산은 담당하지 않습니다.

## 구성요소

```text
HEAPY 클라이언트
  ↓
HEAPY FastAPI
  ↓ 내부 시크릿 + 사용자 JWT
Lambda Function URL
  ├─ Amazon Textract
  ├─ Gemini API
  └─ Supabase Data API
       ├─ master_checkup_item 조회
       └─ create_health_checkup_from_ocr RPC
```

## 추출 흐름

1. HEAPY FastAPI가 로그인 사용자의 JWT와 이미지를 Lambda에 전달합니다.
2. Lambda가 내부 시크릿과 Bearer 토큰 존재를 검사합니다.
3. Textract `AnalyzeDocument`가 표와 양식 관계 및 전체 텍스트 줄을 반환합니다.
4. Gemini가 텍스트에 실제로 존재하는 검진일·기관·검사항목·결과값·단위·판정을 JSON으로 변환합니다.
5. Lambda가 Supabase의 `master_checkup_item`을 조회해 검사명을 `item_code`에 연결합니다.
6. 신뢰도가 낮거나 코드를 찾지 못한 항목에 `needs_review=true`를 표시합니다.
7. 확인용 초안을 반환하며 이 단계에서는 개인 검진 결과를 저장하지 않습니다.

## 저장 흐름

1. 사용자가 확인하거나 수정한 결과를 HEAPY FastAPI가 Lambda에 전달합니다.
2. Lambda가 날짜, 중복 항목, 빈 값, 마스터 코드 존재 여부를 검증합니다.
3. 사용자 JWT로 Supabase RPC를 호출합니다.
4. RPC가 `auth.uid()`를 소유자로 사용해 회차와 결과를 한 트랜잭션으로 저장합니다.
5. 생성한 `record_id`를 반환합니다.

## 장애 경계

- Textract 실패: 저장 없이 `503` 반환
- Gemini 실패: 저장 없이 `503` 반환
- 마스터 매핑 실패: 확인 필요 항목으로 반환
- 사용자 확인 누락: `400` 반환
- JWT 또는 RLS 실패: `401` 반환
- Supabase 저장 실패: 트랜잭션 전체 롤백

## 개인 데이터 보호

이미지는 요청 처리 중 메모리에서만 사용하고 S3나 Supabase Storage에 저장하지 않습니다.
개인 OCR 결과는 캐시하지 않으며 로그에는 요청 식별자와 성공 여부만 기록합니다.
