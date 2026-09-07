# HEAPY OCR Lambda 백엔드 연동 인계서

- 작성자: 김진우
- 작성일: 2026-09-07
- 상태: 구현·로컬 검증 완료, AWS 리소스 생성 및 배포 미실행
- 내부 계약: `1.0` 제안 구현. 아래 미확정 사항은 공개 API 변경 승인으로 간주하지 않는다.

## 1. 확인한 기준 문서와 우선순위

현재 OCR 프로젝트에 `AGENTS.md`, `Reference`, `Reference/rule`은 없다. 대화에 제공된 협업 규칙과 아래 실제 문서를 참조했다. 없는 Reference 파일을 참조했다고 간주하지 않는다.

| 문서 | 적용 범위 |
|---|---|
| `C:/Users/jinwo/heapy-backend/docs/api/HEAPY_BACKEND_API_명세_v1.md` | 공개 API 최우선, 5부 검진·OCR, 복약 OCR, 내부 OCR, 오류·보존 정책 |
| `C:/Users/jinwo/heapy-backend/docs/api/HEAPY_BACKEND_API_검토확정결과.md` | 202 이후 폴링, 확정 멱등성 |
| `C:/Users/jinwo/heapy-backend/docs/architecture/HEAPY_전체_시스템_아키텍처_v1.md` | 앱 → Spring Boot → OCR Lambda, 업무 DB 분리, 미확정 배포 항목 |
| `C:/Users/jinwo/heapy-backend/docs/requirements/HEAPY_화면검토_확정결과.md` | 서버 PDF 변환, 즉시 파일 삭제, 수정 로그·확정값 저장 |
| `C:/Users/jinwo/heapy-backend/docs/requirements/HEAPY_화면_기능_데이터_매핑표.md` | 화면·검토·복약 범위, 후보 API는 확정 계약으로 사용하지 않음 |
| `C:/Users/jinwo/heapy-backend/docs/database/HEAPY_DB_개발기준서_v1.md` | DB 컬럼·FK·보존 정책의 최우선 기준 |
| `C:/Users/jinwo/heapy-backend/docs/database/HEAPY_DB_전체설계_v1.md` | OCR 책임·확정 트랜잭션·보존 범위 |
| `C:/Users/jinwo/heapy-backend/docs/database/HEAPY_DB_물리설계_v1.md` | 이전 상태 열거형과 현재 기준서 차이 확인 |
| `C:/Users/jinwo/heapy-backend/docs/database/HEAPY_DB_ERD_v1.md` | 관계 확인, 기준서와 다른 과거 관계 라벨은 적용하지 않음 |
| `C:/Users/jinwo/heapy-backend/docs/database/HEAPY_DB_마이그레이션_적용결과_v1.md` | 기존 데이터 보존·적용 이력 확인. 이번 작업에서 원격 DB 접근 없음 |
| `README.md`, `docs/건강검진_OCR_공유문서.md` | 기존 데모·Gemini·Vision fallback·복약 구현 파악 |
| `heapy_ocr/catalog.py` | 배포 마스터 스냅샷 158개, 대문자 코드 및 원본 MD5 메타데이터 |

백엔드와 프런트 프로젝트는 수정하지 않았다. 최신 사용자 요청에 따라 데모 UI·서버와 기존 공개 lambda_function.py 진입점을 제거했다. OCR 생성 함수는 heapy_ocr/factory.py로 옮겼으며 배포 진입점은 heapy_ocr.worker.lambda_handler다. 기존 복약 파서는 보존한다.

## 2. 현재 코드와 명세 차이 및 결정 요청

| 항목 | 차이·영향 | 구현과 권고 |
|---|---|---|
| 파일 입력 | 데모는 Base64 페이지 묶음·브라우저 PDF·50MiB, 앱은 multipart·20MB·서버 PDF | 앱은 Spring Boot multipart 유지, Lambda에는 제한된 S3 참조 전달 |
| 내부 경로 | API의 `/internal/ocr`는 FastAPI multipart로 기재, 아키텍처와 이번 요청은 별도 Lambda | 내부 AWS Invoke 어댑터로 대체하는 협업 변경 필요. 공개 URL은 추가하지 않음 |
| 상태 | API와 개발기준서는 `pending`, API 완료는 `completed`; 과거 물리설계는 `queued/review_required` | 내부 `pending/processing/completed/failed` 사용. 백엔드는 실제 CHECK 제약을 확인하고 매핑해야 함 |
| 마스터 | API 예시는 `fasting_glucose`, 현 스냅샷은 `FASTING_GLUCOSE` | 소문자 변환 금지. 백엔드 담당자가 현 마스터의 활성 코드·단위·값 유형을 배포 전에 대조해야 함 |
| 20MB | 명세에 바이트 해석 없음 | `MAX_UPLOAD_BYTES` 필수. `20,000,000` 권고, `20,971,520` 선택도 가능. 기본값으로 확정하지 않음 |
| 결과 TTL | 최대 TTL 미확정 | `MAX_RESULT_TTL_SECONDS` 필수. 1,200초 권고. 인프라 허용 범위 60~86,400초도 운영 제안이며 승인 필요 |
| 암호화 PDF | 데모 비밀번호와 공개 요청 계약 불일치 | 공개 비밀번호 필드 없음. 사용자가 비밀번호 없는 파일만 대상으로 확정했다. 빈 비밀번호 암호화도 처리하지 않고 `ENCRYPTED_PDF_UNSUPPORTED` 반환. 공개 오류 코드 매핑은 백엔드 인계 |
| 손상 파일 | 구체적 공개 오류 매핑 없음 | 손상·복구가 필요한 PDF를 거부하고 `CORRUPT_FILE` 반환. 공개 오류 매핑 확인 필요 |
| 신뢰도 | API 예시에는 확률처럼 보이는 값, 현재 Gemini 구조에는 검증된 신뢰도 없음 | `confidence: null`. 기존 내부 매칭 점수는 인식 확률로 공개하지 않음. nullable 계약 확인 필요 |
| 복약 | 공개 항목은 원문·정규화 용법 문자열, 현재 파서는 구성요소만 추출 | `rawDosage: null`, `normalizedDosage`는 인식된 1회량·횟수·기간·복용법만 조합. 원문 용법 추출 추가는 계약 검토 필요 |

각 목차는 검토용이다. 미확정 정책을 확정하거나 이 문서의 계약을 변경할 때는 해당 목차를 사용자에게 확인받는다. 이번 코드·테스트 작성은 사용자의 즉시 수정 요청에 따라 진행했다.

## 3. 내부 호출 방식 제안

| 방식 | 장점 | 복구·중복 문제 |
|---|---|---|
| 백엔드 실행기에서 동기 Invoke | 초기 브로커 불필요, 작은 완료 응답, 임시 상태로 응답 유실 복구 가능 | 실행기 연결을 오래 유지해야 함. SDK 읽기 시간은 Lambda보다 길게 설정하고 중복 응답을 정상 처리 |
| 비동기 Invoke + 완료 알림 | 실행기 연결 해제 가능 | AWS 재시도와 중복 배달, 알림 유실·재전송·DLQ 필요. 기본 오류 재시도와 삭제된 원본의 재실행이 충돌 |

현재는 동기 `RequestResponse`를 구현한다. 모바일 업로드 HTTP 스레드에서 기다리지 않는다. Spring Boot는 작업을 생성하고 즉시 202를 반환한 뒤 별도 실행기에서 Invoke한다. DB의 미완료 작업 스캔 또는 백엔드의 기존 신뢰 가능한 실행기 복구 기능이 필요하다. 새 업무 테이블·브로커·DB 컬럼을 이 저장소에서 추가하지 않는다.

AWS 공식 확인(2026-09-07): 동기 요청·응답 각각 6MB, 비동기 요청 1MB, 함수 실행 최대 900초. 내부 요청은 8KiB 이하로 제한하는 계약이며 결과는 임시 제어 객체를 포함해 512KiB 이하로 제한한다. 원본·Base64는 Invoke에 넣지 않는다.

- [AWS Lambda 제한](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
- [Invoke API](https://docs.aws.amazon.com/lambda/latest/api/API_Invoke.html)
- [비동기 오류와 재시도](https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-error-handling.html)

## 4. 요청과 임시 제어 객체

백엔드가 인증·소유권·Idempotency-Key 검증 후 UUID jobId를 생성한다. 입력에 사용자 토큰·사용자 ID·DB 키·외부 URL·원본 파일명을 넣지 않는다. 원본 이름 대신 확장자만 보낸다. 버킷은 환경별 허용 버킷 하나로 고정하며 계정 ID도 일치해야 한다.

내부 요청 예시(문서용 합성값, 실제 크기와 SHA-256으로 대체):

```json
{
  "contractVersion": "1.0",
  "jobId": "871f28e6-aec7-41fc-9d5d-02041b3d0d1a",
  "documentType": "health_checkup",
  "inputType": "pdf",
  "createdAt": "2026-09-07T04:00:00Z",
  "expiresAt": "2026-09-07T04:20:00Z",
  "source": {
    "bucket": "환경별-출력값으로-대체",
    "key": "originals/871f28e6-aec7-41fc-9d5d-02041b3d0d1a/source",
    "extension": "pdf",
    "sizeBytes": 1024,
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  }
}
```

필수 필드는 위와 같으며 추가 필드를 거부한다. `documentType`은 `health_checkup/medication`, `inputType`은 `camera/image/pdf`, 확장자는 `jpg/jpeg/png/pdf`만 허용한다. PDF 입력 유형과 확장자는 일치해야 한다. UUID는 정규 소문자 표기, SHA-256은 64자리 소문자 16진수, 크기는 양의 정수다. 시각은 시간대가 있는 ISO 8601이며 생성 시각의 미래 허용 오차는 30초다.

준비 순서:

1. 원본을 `originals/{jobId}/source`에 `If-None-Match: *`, `ServerSideEncryption: AES256`로 업로드한다. 같은 jobId에 덮어쓰기·원본 재생성 금지.
2. `jobs/{jobId}.json`을 `If-None-Match: *`로 생성한다. 구조는 `{"request": 위_요청, "fingerprint": 요청_해시, "status": "pending"}`이다.
3. 요청 해시는 요청 객체의 키를 모든 깊이에서 사전순 정렬하고, 공백 없이 UTF-8 JSON으로 직렬화한 SHA-256이다. Unicode를 ASCII 이스케이프하지 않는다. 기준 구현은 `heapy_ocr.contract.encode`와 `Job.fingerprint`다.
4. DB 작업과 임시 제어 객체 준비가 완료된 작업만 Invoke한다. 준비 중 장애가 나면 백엔드 복구 실행기가 같은 jobId의 상태를 확인하며, 무조건 덮어쓰지 않는다.
5. 응답 유실 시 원본을 다시 업로드하지 말고 `read`로 임시 상태를 확인한다.

Lambda는 ETag `If-Match`로 `pending → processing` 선점을 한 번만 수행한다. 실행 ID·종료 시각을 제어 객체에 기록한다. 결과도 동일 ETag에 대해서만 저장하므로 취소·회수 뒤 완료가 덮어쓰지 못한다. S3 조건부 쓰기를 버킷 정책으로도 요구한다. 제어 객체는 업무 DB가 아니라 최대 TTL이 있는 전용 임시 객체다.

## 5. 응답·조회·정리 계약

완료 Invoke 응답에는 건강정보가 없다.

```json
{
  "contractVersion": "1.0",
  "jobId": "871f28e6-aec7-41fc-9d5d-02041b3d0d1a",
  "status": "completed",
  "error": null,
  "pageCount": 2,
  "expiresAt": "2026-09-07T04:20:00Z"
}
```

백엔드 전용 조회·정리도 같은 비공개 Lambda 별칭을 Invoke한다. `request`에는 최초 요청 객체 전체를 넣는다.

```json
{
  "contractVersion": "1.0",
  "operation": "read",
  "request": {},
  "reason": null
}
```

위 `request: {}`는 자리표시자다. 실제로는 4절 요청 전체가 필요하다. `read`는 완료 응답에 `result`를 추가하고 미완료이면 null이다. `purge`는 `operation: "purge"`, `reason: "confirmed" | "cancelled" | "expired"`를 받는다. 외부 공개 취소·이탈 API 경로를 임의 신설하지 않았으므로 백엔드에서 이탈 통지 방식도 합의해야 한다.

| 내부 상태 | 의미 | 백엔드 책임 |
|---|---|---|
| pending | 임시 객체 준비 완료 | DB 작업 생성 및 202 응답 |
| processing | 한 실행이 선점 | 진행 상태 반영, 동일 요청 중복은 상태 응답으로 취급 |
| completed | 원본 삭제가 확인된 검토 결과 존재 | 현재 DB 작업이 미만료·미확정·유효한 경우에만 공개 완료로 반영 |
| failed | 처리 실패, 결과 없음 | 오류 코드 기록, 사용자 재업로드 판단 |
| cancelled / confirmed | 결과 제거·종료 표시 | 내부 제어 상태이며 DB 열거형을 임의 확장하지 않음 |
| expired | 읽기 차단·결과 제거 | 공개 조회는 410 OCR-003 |

백엔드는 완료 반영·확정·취소를 같은 작업에 대해 직렬화하거나 조건부 갱신한다. 이미 종료된 DB 작업에는 Lambda의 늦은 완료를 적용하지 않는다. 확정 트랜잭션 성공 후 `purge(confirmed)`를 재시도 가능하게 호출하고, 폴링에서는 DB 종료 상태와 만료를 우선 검사한다. purge 실패가 DB 확정을 되돌리지는 않으며 정리 재시도 대상으로 남긴다. 임시 결과의 지연 읽기만으로 작업을 되살리면 안 된다.

## 6. 오류와 재시도

오류는 `{"contractVersion":"1.0","code":"...","retryable":false}` 구조다. 원문 예외·외부 API 응답·파일명·키를 오류 메시지에 싣지 않는다. 아래 공개 매핑은 기존 코드가 있는 경우에 한하며, 새 공개 오류 번호를 만들지 않는다.

| 내부 오류 | 재시도 | 백엔드 공개 처리 |
|---|---|---|
| FILE_LIMIT / PAGE_LIMIT | 아니오 | 413 OCR-001 |
| UNSUPPORTED_FORMAT | 아니오 | 415 OCR-002 |
| EXPIRED | 아니오 | 410 OCR-003 |
| CORRUPT_FILE / ENCRYPTED_PDF_UNSUPPORTED / IMAGE_EXPANSION_LIMIT | 아니오 | 손상·암호화·확장 제한 안내와 공개 코드 합의 필요 |
| SOURCE_NOT_ALLOWED / SOURCE_MISMATCH / JOB_CONFLICT / INVALID_REQUEST | 아니오 | 내부 연동 오류, 원문 없는 운영 경보 |
| JOB_NOT_FOUND | 아니오 | 백엔드 DB에서 만료·정리 여부 확인, 소유권 확인 전 정보 노출 금지 |
| STATE_CONFLICT | 선점 경합이면 가능 | `read`로 현재 상태 확인. 처리 중 취소 경합은 결과 덮어쓰기 금지 |
| TIME_BUDGET | 가능 | 선점 전 제한. 남은 유효기간 안에서 실행기 재호출 |
| INFRASTRUCTURE_FAILED | 가능 | 결과 저장 후 응답 유실일 수도 있으므로 먼저 `read`로 복구 |
| EXTERNAL_SERVICE_FAILED / EXTRACTION_FAILED / PROCESSING_FAILED / PROCESSING_TIMEOUT | 동일 작업 재실행 안 함 | 작업 실패. 외부 장애는 AI-001 후보, 새 업로드 필요 |
| CLEANUP_FAILED | OCR 재실행 안 함 | 결과 공개 차단, 회수기·운영 재시도로 삭제 |
| RESULT_LIMIT | 아니오 | 제한된 응답 크기 초과, 별도 분할 계약 검토 |
| CONFIGURATION_REQUIRED | 아니오 | TTL·파일 한도·비밀 설정 점검 |
| SWEEP_FAILED / SWEEP_INCOMPLETE | 회수기 재시도 | CloudWatch 오류 경보·운영 확인 |

`retryable=true`는 무조건적인 동일 문서 OCR 재처리 허가가 아니다. 최초 선점 후에는 원본을 삭제하므로 자동 재처리를 하지 않는다. processing이 고착되면 회수기가 실패 처리한다. 백엔드는 새로운 사용자 업로드 없이 jobId·만료·fingerprint를 바꾸거나 작업을 재생성하지 않는다.

## 7. 공개 필드·DB 매핑과 정보 손실

| 공개 필드 | 기존 OCR 원천 | DB 확정값 |
|---|---|---|
| measuredAt | measured_at | health_checkup_records.measured_at, 인식 실패 시 null 검토 |
| providerName | hospital_name | health_checkup_records.provider_name |
| items | items/results | 확정 요청의 results로 백엔드가 검증 |
| fieldKey | 결과 순서로 result-1 등 생성 | 수정 로그 field_key, 같은 저장 결과 재조회 시 안정적 |
| itemCode | item_code | master_checkup_item FK, 대소문자 보존 |
| itemName | 표준 이름 또는 미매칭 raw_name | 결과 행에 새 이름 컬럼 추가하지 않음 |
| numericValue | 단일 숫자인 item.value만 파싱 | health_checkup_results.numeric_value |
| value | item.value | health_checkup_results.value, 정성·비교식은 문자 유지 |
| unit | raw_unit | 확정 unit. 환산 없이 표준 단위로 이름만 바꾸지 않음 |
| status | printed_status | 기관 원문 그대로, 누락 시 null |
| confidence | 검증된 원천 없음 | null, 검진 결과에 새 신뢰도 컬럼 없음 |

미매칭 항목은 `itemCode: null`로 검토 목록에 남긴다. DB FK는 NOT NULL이므로 사용자가 활성 마스터를 선택하거나 제외해야 하며 임의 코드 생성은 금지한다. 정성 결과는 마스터에 연결되면 value에 저장할 수 있고 numericValue는 null이다. 동일 회차·동일 코드 유일성도 백엔드가 확인한다.

현재 공개 계약에 없는 `summary_data`, `document_type`, `source_page`, `detail_data`, 원문/표준 단위 쌍, 파서 경고는 임시 앱 결과에 추가하지 않는다. 종합소견·영상 세부소견은 손실된다. 기존 이전 내부 모델의 호환 필드로만 남으며 일반검진 Gemini 요청에서는 추출하지 않는다. 업무 DB JSON 컬럼을 신설하지 않는다. 보존이 필요하면 공개 API와 DB 기준서 승인부터 필요하다.

복약은 기존 5페이지 파서를 앱 경로에서 묶음 호출하여 최대 20페이지를 처리하고 항목 순서를 이어 붙인다. 복약 파서의 묶음당 5페이지 제한과 Gemini 전용 동작은 유지하며 데모 UI는 제거했다. 공개 items의 `rawName`은 raw_name, `normalizedName`은 medicine_name, `normalizedDosage`는 인식된 구성요소로 만든 표시 문자열이다. `rawDosage`와 `confidence`는 원천이 없어 null이다. 함량·처방일·조제일·기관·약국을 위한 공개 필드가 없어 별도 전달하지 않는다. 알림 시각·시작일·종료일을 추측하지 않으며 사용자가 확인한 약·일정·OCR 확정값 저장은 백엔드 책임이다.

## 8. 저장·삭제·자원 제한

- 비공개 S3에 SSE-S3(AES256) 암호화. 버전 관리·복제·Object Lock·원본 백업·S3 접근 로그를 생성하지 않는다. 조직 차원의 AWS Backup, CloudTrail 데이터 이벤트와 보존 정책도 실제 계정에서 확인해야 한다.
- 업로드는 크기와 SHA-256을 검증한다. 실제 JPEG/PNG 디코딩·손상 여부, PDF 헤더·구조·암호화·페이지 수를 확인한다.
- 이미지는 2,500만 픽셀까지, 다중 프레임 거부. PDF는 최대 20페이지·페이지 변 길이 14,400pt까지, 150dpi 상한·긴 변 2,560px로 제한한다. 페이지 JPEG 5MiB·전체 50MiB 제한.
- 처리 자식 프로세스는 Linux 주소공간 1,536MiB·CPU 180초·결과 파일 512KiB 제한. 부모는 전체 처리 780초·Lambda 종료 20초 전·작업 만료 중 가장 이른 시각에 종료한다. 처리 중 2초 간격으로 취소 상태를 확인한다.
- 입력 파일과 자식 결과는 전용 `/tmp/heapy-ocr-*` 안에만 생성한다. 정상·오류·취소 시 자식을 종료한 뒤 폴더를 삭제한다. 변환 이미지는 자식 메모리에만 둔다.
- 원본 S3 삭제 성공 전 완료 결과를 공개하지 않는다. 삭제 실패는 CLEANUP_FAILED이며 결과를 남기지 않는다.
- Lambda 강제 종료 시 `/tmp`는 실행환경에 잔존할 수 있다. 다음 호출 시작 시 전용 임시 폴더를 지우며, 환경이 재사용되지 않는 동안 물리 삭제 시각을 보장하지 않는다. AWS 실행환경 폐기까지의 잔존 위험은 별도 운영 확인 대상이다.
- 1분 주기 회수기가 만료 결과, 종료 작업의 미삭제 원본, lease가 지난 processing, 제어 객체 생성 전 유실된 오래된 원본을 명시적으로 회수한다. 오류 경보와 재시도가 필요하다. 회수량이 실행 시간을 넘으면 경보하며 규모 증가 시 분할·커서 설계가 필요하다.
- 읽기 시 expiresAt 이상이면 즉시 차단하고 결과를 제거한다. 확정·이탈은 백엔드가 purge를 호출한다. 종료 표시 객체는 expiresAt+900초 후 제거해 늦은 실행을 차단한다.
- S3 Lifecycle 2일 삭제·미완료 multipart 1일 중단은 보조 수단이다. 짧은 TTL·즉시 삭제를 보장하지 않는다. [AWS Lifecycle 비동기 삭제 설명](https://docs.aws.amazon.com/AmazonS3/latest/userguide/troubleshoot-lifecycle.html)
- S3 객체 본문·원본은 업무 DB, 로그, ECR 이미지, 테스트 산출물에 포함하지 않는다. 로그는 jobId·처리 시간·오류 코드만 남긴다. 기존 파서 로그는 자식 프로세스에서 비활성화하고 stdout/stderr도 버린다.

## 9. 배포 구성·IAM·출력값

### 9.1 백엔드 전달 사항 반영

사용자가 전달한 백엔드 결정으로 다음 값을 확정한다. 기존 문서의 저장소 논리명 `heapy-ocr`는 실제 저장소 `Heapy-AI/heapy-ocr-lambda`에 대응한다.

| 항목 | 확정값 |
|---|---|
| AWS 리전 | 서울 `ap-northeast-2` |
| AWS 계정 | `577638373354` |
| 백엔드 EC2 | `i-055b8632e5b93fd96` — 사용자 제공, 운영체제·유형은 AWS 조회 전 |
| 백엔드 실행 역할 | `arn:aws:iam::577638373354:role/heapy-backend-dev-ec2-role` |
| 백엔드 공개 주소 | `https://13.125.12.94` — 사용자 제공, 본 작업에서 재시작·변경하지 않음 |
| 백엔드 저장소 | `Heapy-AI/heapy-backend` |
| OCR 저장소 | `Heapy-AI/heapy-ocr-lambda` |
| 개발 배포 | `dev` 브랜치 → GitHub `dev` 환경, 최초 준비·승인 후 자동 배포 |
| 운영 배포 | `main` 브랜치 → 별도 GitHub `production` 환경, 운영 승인 후 배포 |

GitHub 환경 변수 `AWS_REGION`은 두 환경 모두 `ap-northeast-2`, OIDC 템플릿의 `GitHubRepository`는 `Heapy-AI/heapy-ocr-lambda`로 설정한다. 기존 워크플로는 이 변수와 dev/main 환경 분리 구조를 이미 사용한다. 이번 반영은 프로젝트 문서 갱신이며 원격 GitHub 변수·환경이나 AWS 자원을 설정한 것은 아니다.

실제 AWS 배포 전에는 백엔드 실행 역할, OCR 실행 역할, GitHub OIDC 배포 역할의 ARN·신뢰 정책·최소 권한과 Secrets Manager 비밀 ARN·필수 키 이름·접근 권한을 먼저 확인한다. 비밀의 실제 값, EC2 키 파일, 비밀번호를 대화나 Git에 전달하지 않는다. 계정 ID는 확정됐고 지원금 200,000원은 무제한 예산이나 자동 비용 차단 장치가 아니다. 비용 범위·기존 미확정 정책 확인 및 유료 자원 생성 승인도 유지한다.

### 9.2 EC2 생성 여부와 역할 구분

이 OCR 작업에서 EC2를 생성한 적은 없으며, 생성한 EC2 운영체제·인스턴스 유형도 없다. AWS 계정 전체를 조회한 결과는 아니므로 다른 담당자의 생성 여부를 뜻하지 않는다. OCR 배포 단위는 Lambda이고 현재 인프라 코드에 EC2 생성은 포함돼 있지 않다.

아래의 Amazon Linux 2023은 Lambda 컨테이너의 기반 운영체제이며 EC2 선택값이 아니다. 백엔드는 사용자가 제공한 기존 EC2를 사용하며 OCR용 EC2를 추가하지 않는다. 기존 EC2의 운영체제·인스턴스 유형·연결 역할은 읽기 전용 조회 후 확인하며 이 문서에서 추측하지 않는다.

참조: `C:/Users/jinwo/heapy-backend/docs/architecture/HEAPY_전체_시스템_아키텍처_v1.md` 6절 서비스 간 통신, 9절 배포 단위, 10절 구현 전 확정 항목. 리전·실제 저장소·브랜치 구분은 이번 사용자 전달값을 우선한다.

### 9.3 Lambda 구성과 권한

ZIP/Layer는 PDFium 네이티브 라이브러리와 Python ABI·Layer 버전을 함께 관리해야 한다. 컨테이너는 Lambda Linux 기반 이미지 안에서 의존성 설치·합성 렌더 검증을 같은 방식으로 수행할 수 있어 선택했다. Python 3.12 Amazon Linux 2023, linux/amd64를 사용한다. 배포는 ECR digest와 Git 커밋으로 식별한다. [AWS Python 컨테이너](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html)

| 파일 | 역할 |
|---|---|
| infra/registry.yaml | 이름 자동 생성, 암호화·불변 태그 ECR |
| infra/runtime.yaml | 비공개 S3, 최소 실행 역할, OCR·회수 Lambda, live 별칭, EventBridge, 로그·오류 경보 |
| infra/deployment-role.yaml | 해당 저장소·승인 환경 sub와 aud를 제한하는 OIDC 배포 역할 |
| Dockerfile, .dockerignore | 원본·문서·환경파일 없는 실행 이미지 |
| .github/workflows/test.yml | PR 테스트·정적 검사·인프라 검사·Linux 이미지 빌드 및 dev/main 분리 |
| scripts/deploy.py | 새 버전 스모크 후 별칭 전환, 실패 시 이전 live 버전 복구 |

현재 AWS 출력값은 없다. 생성 후 다음 실제 값을 기록한다: `RepositoryUri`, `RepositoryArn`, `OcrBucket`, `WorkerFunctionName`, `WorkerAliasArn`, `JanitorFunctionName`, `WorkerRoleArn`, `SecretArn`, `BackendPolicyArn`, `DeploymentRoleArn`.

Worker IAM은 jobs/ Get·Put, originals/ Get·Delete, 지정 비밀 하나 GetSecretValue, 지정 로그 그룹 쓰기만 허용한다. 회수기는 해당 버킷 prefix List와 객체 회수만 허용하며 비밀 접근은 없다. 백엔드에는 생성된 BackendPolicyArn을 확인된 BackendRoleArn에만 연결한다. 백엔드 업로드·제어 객체 생성과 live Invoke 권한을 포함한다. 사용자·모바일 IAM 자격 증명과 Function URL은 만들지 않는다. 배포 역할의 제한된 스모크 Invoke는 운영 예외이며, 일반 업무 호출자는 백엔드 역할뿐이다. 계정의 기존 광범위 Lambda 권한 역할·조직 정책도 사전 점검한다.

Secrets Manager는 기존 비밀 ARN을 받으며 실제 키 생성·저장은 이번 작업에서 하지 않는다. 비밀 JSON 키는 `GEMINI_API_KEY`, 선택 `GOOGLE_VISION_API_KEY`다. 사용자 관리 KMS 키를 사용한 비밀이라면 해당 KMS 키에 한정한 Decrypt 권한을 추가 검토해야 한다. 현재 템플릿은 기본 Secrets Manager 암호화를 전제로 한다.

필수 런타임 변수는 `OCR_BUCKET`, `AWS_ACCOUNT_ID`, `OCR_SECRET_ARN`, `MAX_UPLOAD_BYTES`, `MAX_RESULT_TTL_SECONDS`, `GEMINI_MODEL`이다. `INTERNAL_SECRET_KEY`는 앱용 Lambda에서 사용하지 않는다. Supabase URL·사용자 토큰·DB 키는 없다.

## 10. 승인 후 준비 순서와 자동 배포

1. 계정·리전·저장소·브랜치는 9.1절 확정값을 사용한다. 실제 배포 전에 인증된 세션의 계정 일치·IAM 역할과 신뢰 정책·비밀 설정·비용 범위를 확인한다. TTL·20MB 기준·암호화 PDF·마스터·nullable 필드 계약을 승인한다.
2. 서울 리전의 Lambda 동시 실행 할당량을 확인한다. OCR 2개·회수 1개의 예약 동시성도 신규 계정에서 실패할 수 있다. 월 비용에는 2GiB OCR 실행 시간, S3 요청·저장, 1분 주기 회수, Secrets Manager, ECR, CloudWatch, Gemini·선택 Vision을 포함한다. 실제 트래픽과 서울 리전 요금 확인 없이 금액을 확정하지 않는다.
3. 승인된 관리 세션에서 registry 스택, 기존 Secrets Manager 비밀과 GitHub OIDC 공급자를 준비한다. ECR 초기 이미지 업로드 권한도 최초 관리 세션에 필요하다. 이미지에 실제 키를 넣지 않는다.
4. Linux 빌드·합성 PDF 검증한 digest를 runtime 스택에 전달한다. 계정·리전·이미지·백엔드 역할·비밀·TTL·용량 기준은 모두 매개변수로 전달한다. 초기 생성은 유료 리소스이므로 승인 후 수행한다.
5. 런타임 출력값으로 deployment-role 스택을 구성한다. OIDC 공급자는 기존 ARN을 재사용하며 중복 생성하지 않는다. 이 배포 역할에는 CloudFormation·IAM 변경·PassRole·비밀 조회 권한이 없다.
6. GitHub `dev` 환경은 dev 브랜치만, `production`은 main만 허용한다. production에는 필수 검토자와 자기 승인 금지를 설정한다. 환경 기반 OIDC sub는 브랜치를 포함하지 않으므로 이 제한이 필수다. [GitHub OIDC·환경 보호](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
7. 환경 변수로 AWS_REGION, AWS_ACCOUNT_ID, AWS_DEPLOY_ROLE_ARN, ECR_REPOSITORY_URI, WORKER_FUNCTION_NAME, JANITOR_FUNCTION_NAME을 설정한다. 비밀키 실제 값은 GitHub에 저장하지 않는다.
8. 사전 확인 후에만 저장소 변수 `AWS_DEPLOYMENT_APPROVED=true`를 설정한다. main은 추가 `PRODUCTION_DEPLOYMENT_APPROVED=true` 및 production 환경 승인이 필요하다. 이 작업에서는 두 변수를 설정하지 않았다. 원격 변수의 현재 값과 실제 Actions 실행 결과는 배포 전 별도로 확인한다.
9. PR에서는 외부 건강 API 호출 없이 테스트·ruff·cfn-lint·Docker 빌드·네트워크 차단 PDF selftest를 실행한다. dev push는 검증 후 개발 환경, main push는 운영 승인 후 별도 환경으로 배포한다. develop은 기존 호환 테스트만 수행한다.
10. 배포 동시성은 브랜치별 직렬화하고 실행 중 배포를 취소하지 않는다. ECR 태그는 커밋 SHA로 불변, Lambda는 digest를 사용한다. 새 숫자 버전에서 합성 PDF selftest를 Invoke한 뒤 live 별칭을 전환한다. 후속 단계 실패 시 이미 전환한 함수들을 이전 버전으로 복구한다.

관리자가 GitHub 실행을 강제로 중단하거나 AWS 권한 장애로 자동 롤백이 실패하면 이전 숫자 버전으로 live 별칭을 수동 복구하고 selftest를 실행한다. 작업 중인 호출은 기존 버전에서 종료될 수 있으므로 계약 하위 호환을 유지한다. 로그의 함수·버전·커밋과 GitHub 배포 이력으로 직전 버전을 확인한다. ECR과 Lambda의 이전 버전은 롤백을 위해 자동 삭제하지 않으며 보관 개수·비용을 승인 후 정한다.

런타임 스택은 초기 인프라와 별칭을 생성하고 이후 코드는 GitHub가 관리하므로 CloudFormation 드리프트가 생긴다. 인프라를 갱신할 때 현재 image digest·별칭 버전을 확인하고 변경 세트에서 별칭 되돌림이 없는지 검토한다. 코드와 인프라 배포를 동시에 실행하지 않는다.

경보는 템플릿에 생성되지만 SNS 수신자·온콜 대상은 아직 정하지 않았다. 운영 시작 전 실제 알림 경로를 연결하고 회수 실패를 합성 장애로 검증해야 한다.

## 11. Git과 검증·미완료 사항

`.env*`, 실제 PDF·이미지, tmp, OCR 결과, 캐시, docs, Reference는 Git 제외 대상이다. `.env.example`, 마스터 코드, 테스트, 의존성 잠금, 인프라, Dockerfile, 워크플로는 포함 대상이다. 기존 추적 파일을 삭제하거나 Git 인덱스에서 제거하지 않았다. docs의 기존 실제 건강 문서는 사용하지 않았다. 사용자가 이번에 지정한 첨부 PDF는 로컬에서만 양식을 확인했고 외부 API로 전송하지 않았다. 검토용 렌더 이미지는 삭제했다.

초기 구현은 커밋 `3569ab7`로 `Heapy-AI/heapy-ocr-lambda`의 `main`에 푸시했다. 이번 배포 대상 확정 사항은 그 이후 문서 갱신이다. 초기 테스트 결과와 변경 목록은 별도 검증 결과 문서에 기록한다. 코드 푸시와 실제 AWS 배포는 구분한다.

초기 커밋의 Linux 이미지 빌드·PDF selftest는 [Actions 실행 34088345390](https://github.com/Heapy-AI/heapy-ocr-lambda/actions/runs/34088345390)에서 성공했고 배포는 건너뛰었다. 현재 보완 코드의 테스트는 56개 통과했다. 상세 검증과 코드별 CI 범위는 검증 결과 문서에 기록한다.

미완료: 사용자 정책 확인, 백엔드 어댑터·상태 갱신·확정 후 정리·이탈 통지 구현, 활성 마스터 대조, GitHub 환경 보호·변수·OIDC 연결, AWS IAM·S3 통합 검증, 비용 승인, 실제 배포. 이 항목들을 배포 완료로 보고하지 않는다.

## 12. 최초 개발 배포 사전 점검과 승인 범위

2026-09-07 읽기 전용 점검에서 로컬 AWS 프로필과 인증 수단을 찾지 못했다. 따라서 계정 내 기존 OCR 자원·OIDC 공급자·역할 정책·비밀·버킷 보존 설정은 미확인이다. 자원이 없다고 단정하지 않으며 인증 연결 후 재사용 가능 여부부터 확인한다. 키 값은 요청하지 않는다.

GitHub에는 환경이 없고 배포 승인 변수도 없었다. 저장소 OIDC 설정은 `use_default=true`, `use_immutable_subject=false`였으며 API가 보고한 prefix는 `repo:Heapy-AI@305710690/heapy-ocr-lambda@1348001285`다. 이 메타데이터만으로 실제 발급 토큰의 sub를 검증했다고 보지 않는다. 기존 템플릿의 환경 기반 `repo:Heapy-AI/heapy-ocr-lambda:environment:dev`와 실제 발급 형식을 배포 전에 대조하고, dev 환경의 허용 브랜치를 dev로 제한한다. 토큰 자체를 로그나 문서에 남기지 않는다.

### 생성·재사용 계획

아래 스택명은 승인용 제안이며 생성된 이름·ARN이 아니다. 실제 버킷·함수·역할 이름은 템플릿 자동 생성값을 사용한다.

| 순서 | 제안 대상 | 변경 범위 |
|---|---|---|
| 1 | 기존 자원 조회 | STS 계정 확인, EC2·연결 역할·기존 정책, OIDC 공급자, OCR 스택·ECR·비밀 메타데이터·동시성 할당량 확인 |
| 2 | `heapy-ocr-dev-registry` | 기존 ECR 재사용 가능 여부를 먼저 확인하고 없으면 registry.yaml로 암호화·불변 태그 저장소 생성 |
| 3 | 서버 비밀 | 기존 비밀 ARN 우선 사용. 신규가 필요하면 별도 승인 후 Secrets Manager 콘솔에서 사용자가 GEMINI_API_KEY와 선택 GOOGLE_VISION_API_KEY 입력. 실제 값 조회·출력 금지 |
| 4 | 초기 이미지 | 관리 세션으로 Linux 검증 완료 커밋 이미지를 ECR에 업로드하고 digest 확인. GitHub 배포 역할 생성 전 단계 |
| 5 | `heapy-ocr-dev-runtime` | runtime.yaml로 비공개 임시 S3, OCR·회수 Lambda와 역할·별칭, 1분 일정, 7일 로그, 경보 생성. 지정 백엔드 역할만 업무 호출 |
| 6 | 백엔드 추가 정책 | 출력 BackendPolicyArn의 버킷 prefix·live Invoke 범위를 검토한 뒤 기존 백엔드 역할에 추가 연결. 기존 SSM·ECR 정책 유지 |
| 7 | `heapy-ocr-dev-deployment` | 기존 OIDC 공급자를 재사용하여 OCR 저장소 dev 환경 전용 역할 생성. 런타임 출력값으로 권한 제한 |
| 8 | GitHub 개발 환경 | dev만 허용하는 환경과 실제 출력 변수 설정. 테스트·IAM·비밀 확인 후 승인받아 개발 배포 플래그 활성화. 운영 플래그는 유지 |
| 9 | 실제 검증 | 숫자 버전 selftest·live 전환·실패 복구 확인, 합성 파일 업로드→Invoke→read→purge 및 원본 삭제 확인 |

처음 생성하는 Lambda에는 이전 정상 버전이 없다. 최초 생성 실패를 이전 버전 롤백 성공으로 보고하지 않는다. 이후 갱신부터 기존 live 버전을 기록하고 실패 시 복구한다. 공개 엔드포인트·새 EC2·업무 DB 변경·백엔드 재시작·기존 자원 삭제는 포함하지 않는다.

### 비용과 보존 확인

주요 비용은 2GiB OCR Lambda 실행 시간·요청, 256MiB 회수기의 1분 실행, S3 임시 저장·Get/Put/List, ECR 이미지 보관, Secrets Manager 비밀·호출, CloudWatch 로그·경보, Gemini 및 선택 Vision이다. 동시성 2는 동시에 실행할 수 있는 수를 제한할 뿐 누적 비용 상한이 아니다. NAT Gateway·API Gateway·OCR EC2는 현재 템플릿에 없다.

[Lambda 요금](https://aws.amazon.com/lambda/pricing/)과 [Secrets Manager 요금](https://aws.amazon.com/secrets-manager/pricing/)을 확인했다. 서울 리전의 실제 사용량·환율·세금·무료 구간·크레딧 적용 여부와 외부 Gemini 비용을 확인하기 전 총액을 약속하지 않는다. 지원금 200,000원과 별개로 예상 월 작업 수·평균 페이지 수 및 알림 수신자를 정해 비용 예상과 경보 범위를 승인받는다.

정상 종료 시 원본은 즉시 삭제하고 결과는 확정·취소 purge로 지운다. TTL 만료 후 읽기는 즉시 거부하며 삭제 실패는 회수 재시도로 넘긴다. 정상적인 회수 일정에서는 만료 후 다음 1분 주기와 스캔·삭제 소요 시간이 추가되며, 고아 원본은 업로드 시각+최대 TTL 이후 회수한다. AWS 장애·권한 장애·스캔 적체 또는 실행환경 미재사용을 포함한 물리적 최대 잔존 시간은 유한한 값으로 보장할 수 없다. Lifecycle 2일도 정확한 삭제 마감이 아니다. 기존 조직의 감사·백업·보존 설정을 조회하고 민감 원본 잔존 여부를 승인 전에 보고하며 보안 설정을 임의 해제하지 않는다.

### 검증 구분과 남은 입력

현재 합성 PDF selftest는 외부 OCR·S3를 호출하지 않는 런타임 스모크다. 이를 Gemini 대역을 사용하는 실제 AWS 저장 흐름 검증 또는 실시간 OCR 성공이라고 부르지 않는다. 실제 AWS 업로드→Invoke→read→purge 성공과 원본·결과 접근 차단은 아직 미검증이며, 실제 Gemini 검증은 비밀·모델·비용 승인 뒤 합성 문서로 수행한다. 백엔드 연동 전에는 모바일 종단 간 완료가 아니다.

AWS 설정은 사용자가 로그인 가능한 콘솔에서 단계별로 진행하기로 했다. 현재 백엔드 실행 역할의 연결 정책 이름을 확인 중이다. 비밀번호 없는 파일만 대상으로 하고 원본 즉시 삭제·일반검진 범위·데모 제거는 사용자 확정 사항이다. 20MB 바이트 기준, 최대 결과 TTL, Gemini 모델·비밀 ARN/준비 여부, 공개 오류 매핑, nullable confidence, 활성 마스터·실제 DB 상태 제약, 이탈 purge 전달 방식은 여전히 미확정이다. 계정·리전·저장소는 다시 묻지 않는다. 실제 조회로 계획을 구체화한 뒤 사용자 승인을 받아 자원 생성·정책 연결·배포 활성화를 진행한다.

배포 출력값 `RepositoryUri`, `OcrBucket`, `WorkerFunctionName`, `WorkerAliasArn`, `JanitorFunctionName`, `WorkerRoleArn`, `DeploymentRoleArn`, `SecretArn`, `BackendPolicyArn`, 이미지 digest와 숫자 배포 버전은 현재 미확인이다. 생성 또는 기존 자원 조회 성공 후 실제 값만 추가한다.


## 13. 일반검진 전용 정리와 AWS 콘솔 첫 단계

코드 커밋 `8ae7b8e`는 dev에 푸시했고 [Actions 34115067807](https://github.com/Heapy-AI/heapy-ocr-lambda/actions/runs/34115067807)에서
56개 테스트와 Linux 이미지 빌드·PDF selftest를 포함한 검증이 성공했다. 배포 단계는 건너뛰었다.

최신 사용자 요청을 우선한다. 일반건강검진 결과통보서의 표에서 실제 검사 결과를 추출한다.
사용자가 지정한 PDF는 암호화되지 않은 4페이지였으며, 일반검진·위험평가와 별도 위암검진
페이지가 함께 있었다. 특정 파일의 페이지 번호를 고정하지 않고 문서 제목·내용으로
일반검진 범위를 구분하도록 Gemini 지침과 텍스트 fallback을 보완했다. 이름·실제 검사값은
코드·테스트·이 문서에 복제하지 않는다.

Gemini 요청 JSON은 `measured_at`, `hospital_name`, `items`로 축소했다. items 원천 필드는
`raw_name`, `raw_value`, `raw_unit`, `printed_status`, `source_page`다. 이전 종합소견·내시경
세부 소견은 추출 대상이 아니다. 백엔드 반환 필드 및 내부 Invoke/read/purge 계약은 유지한다.
예를 들어 아래는 실제 첨부에서 가져오지 않은 합성 검수 결과다.

```json
{
  "measuredAt": "2024-02-03",
  "providerName": "합성검진기관",
  "items": [
    {
      "fieldKey": "result-1",
      "itemCode": "SYSTOLIC_BP",
      "itemName": "수축기혈압",
      "numericValue": 118,
      "value": "118",
      "unit": "mmHg",
      "status": null,
      "confidence": null
    }
  ]
}
```

기준치·빈 체크박스·비해당·위험평가의 목표값·중복값을 결과로 넣지 않도록 지시한다.
일반 청력의 정상/정상은 정성 값이며 주파수 미기재 시 1000Hz 마스터에 자동 연결하지 않는다.
백엔드 활성 마스터에 해당 정성 검사가 없다면 itemCode=null로 검수하고 확정 전 매핑·제외한다.
Vision 텍스트 fallback은 표의 선택 위치를 보장할 수 없는 체크박스 행을 건너뛰므로 일부 결과가
누락될 수 있다. 이미지 기반 Gemini의 선택 인식·범위 제외 정확도는 실제 외부 API로 아직
검증하지 않았다. 프롬프트·합성 파서 테스트 통과를 실제 문서 인식 성공으로 보고하지 않는다.

제거 파일은 demo/index.html, demo/vendor/pdfjs-4.10.38의 라이브러리·라이선스,
demo_server.py, lambda_function.py다. Dockerfile도 해당 공개 진입점을 복사하지 않는다.
복약 OCR 및 기존 API·DB 저장 계약은 유지하며 별도 프런트 화면은 만들지 않는다.

AWS 콘솔 첫 단계는 계정 577638373354·서울 리전을 확인한 뒤 IAM → 역할 →
heapy-backend-dev-ec2-role → 권한에서 연결 정책 이름과 권한 경계 유무를 확인하는 것이다.
정책을 수정하거나 기존 권한을 삭제하지 않는다. 다음으로 기존 OIDC 공급자·비밀 준비 여부를
확인하고 12절 순서대로 생성 대상을 승인받는다. [AWS 역할 권한 확인](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_update-role-permissions.html)

사용자가 콘솔에서 확인해 전달한 연결 정책은 `AmazonSSMManagedInstanceCore`와
`heapy-backend-erc-pull`이다. 두 번째 이름은 사용자 전달 표기를 그대로 기록했다.
정책 본문과 권한 경계는 아직 조회하지 않았으며 이름만으로 실제 허용 범위를 단정하지 않는다.
기존 정책은 유지하고 OCR 자원 생성 후 정확한 버킷 prefix·Lambda live 별칭 권한을 별도 추가한다.
사용자가 IAM 자격 증명 공급자 `token.actions.githubusercontent.com`과 대상
`sts.amazonaws.com`이 있다고 확인했다. 이후 서울 리전에 개발 비밀을 생성하고 다음 ARN을 전달했다.

- SecretArn: `arn:aws:secretsmanager:ap-northeast-2:577638373354:secret:heapy/dev/ocr-yHbFSW`
- ARN 형식·계정·리전은 일치한다. 실제 비밀 내용·암호화 설정·Lambda 접근 권한은 미검증이다.
- 사용자가 기존 OCR용 ECR이 없다고 확인하고, 생성 승인·콘솔 절차 진행 후 다음 RepositoryUri를 전달했다.
- RepositoryUri: `577638373354.dkr.ecr.ap-northeast-2.amazonaws.com/heapy-ocr-dev-registry-repository-sprmdejyled7`
- 이미지 업로드·Lambda 배포는 아직 하지 않았다. 다음 단계는 최초 이미지 업로드용 GitHub OIDC 인증 준비다.
- 실제 GitHub OIDC 발급 확인 결과 접두사는 `repo:Heapy-AI@305710690/heapy-ocr-lambda@1348001285`다.
  초기 메타데이터 기반의 이름만 포함된 sub 제안은 사용하지 않는다. image-push-role.yaml과
  deployment-role.yaml의 GitHubSubjectPrefix에 이 값을 전달한다. 확인 근거·권한·입력값은
  `AWS_최초_이미지_업로드_역할_확인.md`에 기록했다. AWS 역할은 아직 생성하지 않았다.
  이후 사용자 승인으로 생성 시도했으나 IAM Description의 한글 문자 제약으로 실패했다.
  설명만 수정했으며 권한은 그대로다. 테스트 60개와 인프라 검사를 통과했고,
  기존 실패 스택은 유지하며 `heapy-ocr-dev-image-push-role-r2`로 같은 역할 생성을 재시도한다.
  이후 사용자가 CREATE_COMPLETE를 확인하고 실제 역할 ARN
  `arn:aws:iam::577638373354:role/heapy-ocr-dev-image-push-role-ImagePushRole-Jn1OXuDIMRn2`를 전달했다.
  이 실제 ARN을 사용한다. r2는 제안명이며 실제 생성 이름으로 단정하지 않는다.
  다음 단계는 `AWS_최초_이미지_업로드_실행_확인.md` 범위의 GitHub Actions 최초 이미지 업로드다.

원본 즉시 삭제를 위해 신규 임시 버킷은 버전 관리·복제·Object Lock 없이 계획한다.
기존 버킷을 재사용한다면 과거 버전까지 먼저 확인한다. 버전 관리 버킷의 일반 DeleteObject는
이전 버전을 지우지 않고 삭제 표시만 만들 수 있으므로 삭제 성공만으로 영구 삭제를 주장하지
않는다. [AWS DeleteObject 동작](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObject.html)
