# HEAPY OCR Lambda

건강검진 결과지 사진에서 텍스트와 검사 결과를 추출하고, 사용자가 확인한 결과를
Supabase의 `health_checkup_records`, `health_checkup_results`에 저장하는 독립 Lambda
서비스입니다.

- 작성자: 김진우
- 지원 OCR 유형: `HEALTH_CHECKUP`
- 실행 방식: AWS Lambda Function URL
- OCR: Amazon Textract `AnalyzeDocument(TABLES, FORMS)`
- 구조화 파싱: Gemini JSON 구조화 출력
- 저장: 사용자 JWT + Supabase RLS + 원자적 RPC

## 처리 흐름

```text
HEAPY 백엔드
  └─ EXTRACT 요청
       ├─ 내부 시크릿과 사용자 JWT 검증
       ├─ Textract 표·양식 OCR
       ├─ Gemini 건강검진 항목 구조화
       ├─ master_checkup_item 코드 매핑
       └─ 사용자 확인용 초안 반환

사용자 확인
  └─ CONFIRM_AND_SAVE 요청
       ├─ 날짜·항목 코드·결과값 검증
       └─ Supabase RPC로 검진 회차와 결과를 한 트랜잭션에 저장
```

OCR 결과는 자동 저장하지 않습니다. 숫자·항목·검진일을 사용자가 확인한 뒤
`confirmed=true` 요청을 보내야 저장됩니다.

## 프로젝트 구조

```text
heapy-ocr-lambda/
├── lambda_function.py
├── heapy_ocr/
│   ├── config.py
│   ├── gemini.py
│   ├── matcher.py
│   ├── models.py
│   ├── service.py
│   ├── supabase.py
│   └── textract.py
├── database/
│   └── create_health_checkup_from_ocr.sql
├── docs/
│   ├── api_spec.md
│   ├── architecture.md
│   └── db_design.md
└── tests/
```

## 환경변수

`.env.example`을 기준으로 Lambda 환경변수를 설정합니다.

| 환경변수 | 설명 |
|---|---|
| `INTERNAL_SECRET_KEY` | HEAPY 백엔드와 Lambda가 공유하는 내부 인증 키 |
| `GEMINI_API_KEY` | Gemini 구조화 파싱 API 키 |
| `GEMINI_MODEL` | 기본값 `gemini-2.5-flash` |
| `SUPABASE_URL` | HEAPY Supabase 프로젝트 URL |
| `SUPABASE_PUBLISHABLE_KEY` | 공개 가능한 publishable key. 사용자 JWT와 함께 사용 |
| `MAX_IMAGE_BYTES` | 기본 5 MiB |
| `EXTERNAL_TIMEOUT_SECONDS` | 외부 API 호출 제한 시간, 기본 20초 |

`service_role` 또는 secret key는 사용하지 않습니다.

## 사전 DB 설정

`database/create_health_checkup_from_ocr.sql`을 HEAPY Supabase 프로젝트에 적용해야 합니다.
이 SQL은 사용자 본인 행만 삽입할 수 있는 RLS 정책과 저장 RPC를 추가합니다.

## 테스트

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

실제 사진 테스트는 다음 순서로 진행합니다.

1. HEAPY에 로그인해 사용자 access token을 준비합니다.
2. 결과지 이미지를 Base64로 변환합니다.
3. `EXTRACT` 요청을 보내고 항목·수치·검진일을 확인합니다.
4. 필요 항목을 수정한 뒤 `CONFIRM_AND_SAVE` 요청을 보냅니다.
5. `record_id`로 Supabase 저장 결과를 조회합니다.

요청과 응답 예시는 [API 명세](docs/api_spec.md)에 있습니다.

## 보안 원칙

- Base64 이미지와 전체 OCR 텍스트를 로그에 남기지 않습니다.
- 응답에 `Cache-Control: no-store`를 설정합니다.
- 사용자 JWT를 Supabase에 그대로 전달해 RLS를 적용합니다.
- OCR 추출과 DB 저장을 분리합니다.
- 인식되지 않은 항목 코드와 빈 결과값은 저장하지 않습니다.
- 건강검진 수치로 판정을 새로 계산하지 않고 결과지에 인쇄된 판정만 저장합니다.

## HEAPY 문서 정합성

구현 전 다음 HEAPY 문서를 확인했습니다.

- `docs/api_spec.md`: 사용자 JWT와 개인 건강검진 컨텍스트 계약
- `docs/README.md`: 개인 RDB 데이터 비캐시 원칙과 시스템 아키텍처
- `docs/node_io_spec.md`: 검진 회차·항목·값·저장 상태 계약
- `docs/pipeline_state_design.md`: 개인 데이터와 공용 지식의 분리
- `docs/supabase_auth_chat_db_design.md`: 건강검진 테이블 관계와 RLS
- `docs/medical_term_db_design.md`: 표준용어는 정규화 용도이며 의료 판단을 생성하지 않는 원칙

기존 HEAPY 작업공간에는 `Reference` 폴더가 없어 위 `docs` 대응 문서를 기준으로
정합성을 점검했습니다.
