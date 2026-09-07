# HEAPY OCR Lambda

- 작성자: 김진우
- 범위: Spring Boot가 전달한 일반건강검진 문서를 OCR하고 검수용 JSON 반환
- 진입점: `heapy_ocr.worker.lambda_handler`
- 개발: `dev`, 서울 `ap-northeast-2` / 운영: `main`, 별도 승인
- 실제 AWS 배포: 아직 진행하지 않음

## 처리 흐름

Spring Boot 파일 접수 → 비공개 S3 원본 임시 업로드 → IAM Lambda Invoke →
이미지 검증·PDF 서버 변환 → Gemini 일반검진 구조화·마스터 매칭 → 원본 삭제 →
임시 결과 저장 → Spring Boot read → 사용자 확정 뒤 purge.

앱은 Spring Boot만 호출합니다. Lambda는 사용자 인증·업무 DB 저장·사용자 확정을 수행하지 않습니다.
파일 바이트나 Base64를 Invoke에 넣지 않으며 Function URL·공개 API·데모 UI는 없습니다.
기존 복약 OCR 모듈은 보존하지만 이번 검토·개발 연동은 일반검진을 우선합니다.

## 일반검진 파싱

일반건강검진 결과통보서의 검사 결과 표를 대상으로 합니다. 키·몸무게, 혈압과 시력의
분리 값, 실제 검사 수치·단위, 선택된 판정, 정성 결과를 추출합니다. 암검진 별지·
내시경 상세 소견과 위험평가의 목표값·중복값은 대상에서 제외합니다.

외부 JSON은 `measuredAt`, `providerName`, `items`를 유지합니다. 항목에는
`fieldKey`, `itemCode`, `itemName`, `numericValue`, `value`, `unit`, `status`,
`confidence`가 있습니다. 알 수 없는 값은 추정하지 않으며 신뢰도는 null입니다.
마스터에 없는 일반 청력 판정은 미매칭으로 전달하고 1000Hz·dB 검사로 단정하지 않습니다.

Gemini 실패 시 해당 페이지 묶음만 선택적 Vision·규칙 파서로 처리합니다.
규칙 fallback은 텍스트에서 체크박스 위치를 보장할 수 없는 행을 건너뜁니다.
실제 외부 API 인식 정확도는 아직 검증하지 않았으며 사용자 검수가 필요합니다.

## 파일과 보존

JPG/JPEG/PNG/PDF, 최대 20MB·PDF 20페이지를 검증합니다. 20MB의 바이트 수와
최대 결과 TTL은 배포 매개변수로 확정해야 합니다. 비밀번호 없는 PDF만 지원하며
암호화 파일은 `ENCRYPTED_PDF_UNSUPPORTED`로 거부합니다. 비밀번호 필드는 없습니다.

원본은 성공·실패 직후 삭제하며 변환 이미지는 작업 메모리에서만 사용합니다.
원본 삭제 실패 시 완료 결과를 공개하지 않고 회수기가 재시도합니다. 강제 종료·고아 파일도
회수합니다. 결과는 확정·취소·만료 시 제거하고 만료된 결과의 읽기는 즉시 차단합니다.
Lifecycle만으로 즉시 삭제를 보장하지 않습니다.

## 설정과 검증

값 없는 `.env.example`에 필요한 환경변수 이름이 있습니다. 운영 키는 Secrets Manager의
`GEMINI_API_KEY`, 선택 `GOOGLE_VISION_API_KEY`로 관리하며 Git·이미지·로그에 넣지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\cfn-lint.exe infra/runtime.yaml infra/registry.yaml infra/deployment-role.yaml
```

```sh
docker build --platform linux/amd64 --provenance=false -t heapy-ocr-test .
docker run --rm --network none --entrypoint python heapy-ocr-test -m heapy_ocr.selftest
```

테스트는 합성 데이터를 사용합니다. 실제 문서·변환 이미지·OCR 결과·환경 비밀은 Git 제외 대상입니다.
컨테이너 selftest는 PDF 의존성 검사이며 실제 S3·Gemini 종단 간 성공을 뜻하지 않습니다.

## 인계 문서

- [백엔드 연동 인계서](백엔드_OCR_Lambda_연동_인계서.md): 내부 요청·응답, IAM·정리 책임, 최초 배포 순서
- [구현·검증 결과](OCR_Lambda_구현_검증결과.md): 변경과 실제 검증 범위

현재 프로젝트에는 AGENTS.md·Reference·Reference/rule이 없습니다. 실제 대조한
백엔드 API·시스템 아키텍처·요구사항·DB 문서 목록은 인계서 1절에 기록했습니다.
