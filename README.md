# HEAPY OCR Lambda

건강검진 결과지의 한글·영문 텍스트를 인식하고 정해진 결과 구조로 변환하는 OCR 전용
프로젝트입니다.

- 작성자: 김진우
- 지원 유형: `HEALTH_CHECKUP`, `MEDICATION`
- OCR: Google Cloud Vision `DOCUMENT_TEXT_DETECTION`
- 구조화: Gemini 구조화 파서 우선, 내부 규칙 파서 fallback
- 항목 매칭: 내부 건강검진 마스터 158개
- DB 연결 및 저장: 지원하지 않음
- Supabase 사용자 토큰: 필요 없음

## 처리 흐름

```text
JPG·PNG 또는 PDF
  → PDF 페이지 이미지 변환
  → Google Vision 한글 OCR
  → OCR 텍스트를 기본 3페이지씩 Gemini 구조화
  → 실패한 페이지 묶음만 내부 규칙 파서 fallback
  → 내부 건강검진 마스터 코드 매칭
  → JSON 결과 반환
```

이미지, PDF, OCR 결과는 DB나 파일에 저장하지 않습니다.

## 환경변수

| 환경변수 | 설명 |
|---|---|
| `INTERNAL_SECRET_KEY` | Lambda 호출 시 HEAPY 백엔드와 공유하는 내부 키 |
| `GOOGLE_VISION_API_KEY` | Google Cloud Vision API 키 |
| `GEMINI_API_KEY` | Gemini API 키, 없거나 호출 실패 시 규칙 파서로 자동 전환 |
| `GEMINI_MODEL` | Gemini 모델, 기본 `gemini-2.5-flash` |
| `GEMINI_PAGES_PER_REQUEST` | Gemini 요청당 페이지 수, 기본 3, 허용 1~5 |
| `MAX_IMAGE_BYTES` | 이미지 한 장의 최대 크기, 기본 5 MiB |
| `EXTERNAL_TIMEOUT_SECONDS` | 외부 API 제한 시간, 기본 20초 |
| `GEMINI_TIMEOUT_SECONDS` | Gemini 제한 시간, 기본 60초 |

Supabase URL, publishable key, access token은 설정하지 않습니다.

## 로컬 데모 실행

프로젝트 루트의 `.env`에 키를 입력합니다.

```env
GOOGLE_VISION_API_KEY=새로_발급한_Vision_키
GEMINI_API_KEY=새로_발급한_Gemini_키
```

`.env`는 Git에 포함되지 않으며 로컬 데모 시작 시 자동으로 읽습니다. 이미 설정된 터미널
환경변수가 있으면 터미널 값을 우선합니다.

```powershell
.\.venv\Scripts\python.exe demo_server.py
```

약봉투를 시험하려면 브라우저에서 `약봉투 · 복약안내문`을 선택하고 JPG 또는 PNG 사진을
올린 뒤 `전체 로직 실행`을 누릅니다. 약명, 함량, 1회량, 1일 횟수, 투약일수와 복용법이
표와 JSON으로 표시됩니다.

브라우저에서 `http://127.0.0.1:8080`을 엽니다. JPG, PNG, PDF와 암호화된 PDF를
지원하며 PDF는 브라우저 메모리에서 최대 20페이지의 이미지로 변환합니다. 페이지 이미지는
한 장씩 Vision OCR로 전송하고, OCR 텍스트는 기본 3페이지 단위로 나눠 Gemini에
전송합니다. 특정 묶음의 Gemini 호출만 실패하면 해당 묶음에만 규칙 fallback을 적용합니다.

- `원문 OCR 실행`: Google Vision 결과만 확인
- `전체 로직 실행`: Vision OCR, Gemini 우선 구조화, 규칙 fallback, 내부 코드 매칭까지 확인

두 기능 모두 사용자 토큰이나 DB 연결을 사용하지 않습니다.

약봉투는 양식별 차이가 커서 Gemini 전용 파서를 사용하며 현재 규칙 fallback은 적용하지
않습니다. Gemini를 호출할 수 없으면 잘못된 복약 정보를 임의 생성하지 않고 오류를
반환합니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

## 문서

- [API 명세](docs/api_spec.md)
- [시스템 아키텍처](docs/architecture.md)
- [요구사항](docs/requirements.md)
- [DB 설계 범위](docs/db_design.md)

현재 저장소에는 `Reference` 폴더가 없어 위 문서를 구현 기준으로 사용합니다.
