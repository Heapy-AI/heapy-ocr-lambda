# HEAPY OCR Lambda 구현·검증 결과

- 작성자: 김진우
- 작성일: 2026-09-07
- 실제 배포 상태: 미배포, AWS 리소스 생성·원격 DB 변경·Git 커밋·푸시 없음

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
| `python -m pytest -o addopts= -q` | 43개 통과, 마지막 실행 1.70초 |
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

- 로컬 Docker 실행 파일이 없어 실제 Lambda Linux 이미지 빌드·실행은 미검증이다. PR에서 컨테이너를 빌드하고 네트워크 없이 selftest를 실행하도록 설정했다. PR 실행 결과를 아직 얻은 것은 아니다.
- AWS 계정·리전·권한·비용 승인이 없어 실제 Lambda·S3·Secrets Manager·OIDC·EventBridge·CloudWatch 통합 및 배포·실환경 롤백은 미검증이다.
- 실시간 Gemini·Vision 응답과 인식 품질·20페이지 최대 부하 측정은 수행하지 않았다. 실제 건강 문서를 외부로 전송하지 않았다.
- 현재 마스터는 OCR 저장소 스냅샷이며 백엔드 지정 경로의 검색에서 대조할 별도 코드 seed를 찾지 못했다. 활성 마스터·대소문자·표준 단위·값 유형은 백엔드 담당자의 최신 기준 대조가 필요하다.
- TTL, 20MB 바이트 기준, 암호화·손상 파일의 공개 오류 처리, nullable 신뢰도·복약 원문 용법, 이탈 통지는 확인 대기다. 임의로 공개 계약을 확정하지 않았다.
- GitHub 환경 보호·변수·승인자 설정, 최초 리소스 생성, 경보 수신자 연결, 조직 차원의 버전·복제·백업·로그 잔존 검토가 필요하다.

## 5. 참조와 인계

참조 목록과 우선순위는 [백엔드 연동 인계서](백엔드_OCR_Lambda_연동_인계서.md) 1절에 기록했다. 공개 계약은 `HEAPY_BACKEND_API_명세_v1.md`, 저장 규칙은 `HEAPY_DB_개발기준서_v1.md`를 우선하며 API 검토확정결과·전체 아키텍처·요구사항 2개·DB 설계/물리설계/ERD/마이그레이션 적용결과 및 기존 OCR 공유문서와 대조했다. 현재 프로젝트의 Reference와 협업 규칙 파일 부재도 명시했다.

백엔드·프런트는 수정하지 않았다. 백엔드 실행기·조건부 DB 상태 반영·소유권·확정 트랜잭션·purge 재시도·모바일 202/폴링 유지는 해당 담당자에게 인계한다. 배포 완료 상태가 아니다.
