# HEAPY OCR Lambda 구현·검증 결과

- 작성자: 김진우
- 작성일: 2026-09-07
- 실제 배포 상태: 미배포. 초기 구현은 `3569ab7`로 main에 푸시했다. 이번 보완은 해당 커밋에서 분기한 dev에서 진행한다. AWS 리소스 생성·원격 DB 변경 없음.

## 1. 적용 내용

앱용 비공개 Lambda 진입점, 허용 S3 객체 검증, 서버 PDF 변환, Gemini·건강검진 부분 Vision fallback 재사용, 제한된 앱 결과 매핑, ETag 기반 중복 방지·취소·만료·명시적 삭제·주기적 회수를 구현했다. 업무 DB 접근과 사용자 토큰 요구는 없다.

Lambda Linux 컨테이너, 고정 의존성, CloudFormation 인프라 3종, GitHub OIDC 개발·운영 배포 분리, 새 버전 스모크·live 전환·롤백을 작성했다. 계정·리전·정책 확인 전 배포되지 않도록 승인 변수를 필수로 두었다.

## 2. 이번 변경 파일

| 파일 | 변경 내용 |
|---|---|
| heapy_ocr/contract.py | 버전·필수 필드·8KiB 요청·허용 객체·TTL·해시 계약 |
| heapy_ocr/files.py | JPEG/PNG 디코딩, PDF 구조·암호화·20페이지·확장 제한, 서버 변환 |
| heapy_ocr/app_mapping.py | 공개 필드 매핑, 미매칭·정성 결과, 원문 단위, 신뢰도 null, 모호한 숫자 추정 금지 |
| heapy_ocr/processor.py | 메모리·CPU 제한 자식 프로세스, 기존 건강검진·복약 서비스 재사용 |
| heapy_ocr/storage.py | 제한된 S3 읽기·해시 검사·조건부 갱신·삭제 |
| heapy_ocr/worker.py | Invoke, 선점, 상태·조회·정리, 자식 종료, 잔존 임시 폴더 회수, 비밀 로딩 |
| heapy_ocr/janitor.py | 만료·강제 종료·고아 원본 회수 및 실패 신호 |
| heapy_ocr/selftest.py | 외부 API 없는 합성 PDF 런타임 스모크 |
| tests/test_app_worker.py | 파일·중복·만료·취소·정리·자식 프로세스·회수 테스트 |
| tests/test_integration_boundaries.py | fallback·매핑·S3 SDK·배포 롤백 경계 테스트 |
| tests/test_direct_gemini.py | 기존 파일 보존, tests Git 제외 해제로 추적 가능하게 변경 |
| infra/runtime.yaml | S3·IAM·Lambda·별칭·회수 일정·오류 경보·처리 실패 지표 |
| infra/registry.yaml | 암호화 ECR·불변 태그·Lambda 이미지 읽기 정책 |
| infra/deployment-role.yaml | 저장소·환경 한정 OIDC 및 코드 배포 최소 권한 |
| scripts/deploy.py | 버전 스모크·별칭 전환·실패 롤백 |
| Dockerfile, .dockerignore | Python 3.12 Lambda Linux 이미지, 민감 파일 빌드 제외 |
| requirements.txt, requirements.lock | 직접·간접 런타임 의존성 고정 |
| requirements-dev.txt, requirements-dev.lock | 검사·테스트 도구 직접·간접 의존성 고정 |
| .github/workflows/test.yml | PR 검사·이미지 검증·dev 자동 배포·main 승인 분리 |
| .gitignore, .env.example | 민감 파일·캐시 제외, 값 없는 설정 예시 |
| README.md | 기존 내용을 보존하며 앱 진입점·검증·인계서 안내 추가 |
| 백엔드_OCR_Lambda_연동_인계서.md | 참조 문서, 계약·차이·백엔드 책임·배포 사전 준비 |
| OCR_Lambda_구현_검증결과.md | 현재 문서 |

작업 시작 전부터 사용자 변경이 있던 `README.md`, `demo/index.html`, `heapy_ocr/gemini.py`, `matcher.py`, `medication.py`, `medication_service.py`, `models.py`, `rule_parser.py`, `service.py`, `lambda_function.py`는 되돌리지 않았다. 이 중 이번 작업에서 직접 변경한 기존 사용자 수정 파일은 README의 앱 연동 안내 추가뿐이다. Git diff 전체를 이번 구현의 변경량으로 해석하면 안 된다.

## 3. 실행한 검증

| 검증 | 결과 |
|---|---|
| `python -m pytest -o addopts= -q` | 이번 일반검진 보완 코드 56개 통과, 2.33초 |
| `python -m ruff check .` | 통과 |
| `cfn-lint infra/runtime.yaml infra/registry.yaml infra/deployment-role.yaml` | 3개 템플릿 통과 |
| `python -m heapy_ocr.selftest` | 합성 PDF 2페이지 변환 성공 |
| `python -m pip check` | 의존성 충돌 없음 |
| `git diff --check` | 공백 오류 없음. 기존 Windows CRLF 안내만 발생 |
| Git 제외 확인 | .env·docs·tmp·캐시 제외, .env.example·테스트·잠금·인프라는 제외되지 않음 |
| 기존 민감 파일 추적 여부 | .env·docs·Reference에 현재 추적 파일 없음, 추적 파일 임의 삭제 없음 |

환경은 로컬 Windows Python 3.11이며 배포 대상은 Python 3.12 Lambda Linux다. 설치 패키지의 PDFium/Pillow 실제 디코더와 자식 프로세스를 로컬에서 실행했다. AWS SDK 경계는 Stubber로 검증했고 실제 S3·IAM을 호출하지 않았다.

테스트는 합성 이미지·빈 PDF와 메모리 대역만 사용했다. JPG/JPEG/PNG, 20페이지 PDF, 21페이지 거부, 손상·형식 불일치·암호화·파일 제한·픽셀 확장 제한, 외부 실패·부분 fallback, 정성·미매칭·원문 단위·모호한 수치, 중복 선점·만료 삭제·취소 후 늦은 완료, 실패 정리·삭제 실패 결과 차단, 고착 실행 회수·전용 임시 디렉터리 회수, S3 ETag 충돌·해시 불일치, 배포 도중 실패한 함수의 이전 별칭 복구를 검증했다.

## 4. 아직 검증하지 못한 사항

- 초기 커밋 `3569ab7`의 [Actions 실행 34088345390](https://github.com/Heapy-AI/heapy-ocr-lambda/actions/runs/34088345390)은 테스트·Lambda Linux 이미지 빌드·이미지 내부 합성 PDF selftest가 성공했고 배포 단계는 건너뛰었다. 이번 보완 코드의 Linux 검증은 별도 CI 결과로 판단한다. 로컬에는 Docker가 없다.
- AWS 계정 `577638373354`와 서울 리전은 확정됐지만 현재 세션의 AWS 프로필·자격 증명이 없고 브라우저에도 AWS 연결 세션이 없다. 실제 Lambda·S3·IAM·Secrets Manager·EventBridge·CloudWatch 조회·통합·배포·실환경 롤백은 미검증이다.
- 실시간 Gemini·Vision 응답과 인식 품질·20페이지 최대 부하 측정은 수행하지 않았다. 실제 건강 문서를 외부로 전송하지 않았다.
- 현재 마스터는 OCR 저장소 스냅샷이며 백엔드 지정 경로의 검색에서 대조할 별도 코드 seed를 찾지 못했다. 활성 마스터·대소문자·표준 단위·값 유형은 백엔드 담당자의 최신 기준 대조가 필요하다.
- TTL, 20MB 바이트 기준, 암호화·손상 파일의 공개 오류 처리, nullable 신뢰도·복약 원문 용법, 이탈 통지는 확인 대기다. 임의로 공개 계약을 확정하지 않았다.
- GitHub 환경 보호·변수·승인자 설정, 최초 리소스 생성, 경보 수신자 연결, 조직 차원의 버전·복제·백업·로그 잔존 검토가 필요하다.

## 5. 참조와 인계

참조 목록과 우선순위는 [백엔드 연동 인계서](백엔드_OCR_Lambda_연동_인계서.md) 1절에 기록했다. 공개 계약은 `HEAPY_BACKEND_API_명세_v1.md`, 저장 규칙은 `HEAPY_DB_개발기준서_v1.md`를 우선하며 API 검토확정결과·전체 아키텍처·요구사항 2개·DB 설계/물리설계/ERD/마이그레이션 적용결과 및 기존 OCR 공유문서와 대조했다. 현재 프로젝트의 Reference와 협업 규칙 파일 부재도 명시했다.

백엔드·프런트는 수정하지 않았다. 백엔드 실행기·조건부 DB 상태 반영·소유권·확정 트랜잭션·purge 재시도·모바일 202/폴링 유지는 해당 담당자에게 인계한다. 배포 완료 상태가 아니다.

## 6. 기존 구현 재점검과 보완

- 만료 판정을 제어 객체 읽기보다 먼저 수행한다. 제어 객체가 없거나 삭제가 실패하더라도 read는 EXPIRED를 반환하고 execute는 재실행하지 않는다. 회수 장애는 건강정보 없는 CLEANUP_FAILED 로그로 남기며 회수기가 재시도한다.
- purge는 이미 confirmed·cancelled·expired인 종료 상태를 다른 종료 상태로 바꾸지 않는다. 원본 삭제는 다시 시도하되 제거할 결과가 없으면 불필요한 조건부 갱신을 하지 않는다.
- 동시 호출 두 개가 같은 pending ETag를 읽도록 강제한 테스트에서 한 호출만 OCR을 수행하고 다른 호출은 STATE_CONFLICT를 받는지 검증했다.
- 고아 원본은 최대 TTL을 넘은 객체만 회수하고 최근 업로드는 유지하는지, 삭제 장애 시 SWEEP_FAILED를 발생시키는지 검증했다. 모두 합성·메모리 대역이며 실제 AWS 성공을 뜻하지 않는다.
- GitHub 원격에는 점검 시 main만 있었고 로컬 dev를 main의 기존 구현에서 분기했다. GitHub 환경은 없었으며 배포 승인 변수도 설정되지 않았다. 환경·IAM·배포 활성화는 변경하지 않았다.


## 7. 일반검진 전용 정리 결과

- 최신 사용자 요청으로 데모 UI·PDF.js·데모 서버·공개 lambda_function.py를 제거했다.
  OCR 서비스 생성은 factory.py로 분리하고 Dockerfile·processor.py의 데모 의존성을 없앴다.
  config.py의 공유 내부 키 설정도 제거했다. 기존 복약 파서는 유지한다.
- general_checkup.py와 Gemini 스키마·프롬프트를 일반검진 표 중심으로 보완했다.
  별도 암검진과 위험평가 중복값 제외, 체크된 판정만 사용, 참고치 제외, 합성 JSON 매핑을 검증했다.
- 일반 청력은 주파수가 없으면 특정 1000Hz 마스터로 추정하지 않는다. 텍스트 fallback은
  체크박스 위치가 모호한 행을 보수적으로 제외한다. 실제 이미지 인식 품질은 미검증이다.
- 비밀번호 없는 파일만 대상으로 확정하여 암호화 PDF는 ENCRYPTED_PDF_UNSUPPORTED로 거부한다.
  공개 비밀번호 필드는 없으며 공개 오류 매핑은 백엔드 인계 대상이다.
- 첨부 PDF를 로컬 렌더링해 4페이지 양식을 확인했다. 외부 OCR API 호출·AWS 업로드는 없으며
  실제 수검자 정보·검사값을 테스트에 복제하지 않았다. 렌더링 임시 이미지 4개는 삭제했다.
- tests/test_general_checkup.py의 합성 검증 5개를 추가했다. 총 56개 통과·Ruff 통과다.
  현재 변경분은 로컬 검증이며 초기 커밋의 Linux CI 결과를 대신 사용하지 않는다.
- AWS는 사용자의 콘솔 로그인 경로로 진행하며 백엔드 실행 역할의 연결 정책을 확인하는 단계다.
  IAM 정책 연결·비밀 생성·유료 자원 생성·배포 활성화는 수행하지 않았다.
