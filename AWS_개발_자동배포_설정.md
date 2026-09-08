# 개발 자동 배포 설정

- 작성자: 김진우
- 작성일: 2026-09-08
- 범위: Heapy-AI/heapy-ocr-lambda의 dev 개발 배포. 운영은 별도 승인.

## 1. GitHub 준비

dev 환경을 만들고 배포 허용 규칙을 이름 dev, 유형 branch 하나로 제한했다.
계정·리전·ECR URI·Worker·Janitor 이름을 dev 환경 변수로 저장했다.
사용자가 전달한 배포 역할 ARN을 AWS_DEPLOY_ROLE_ARN에 등록하고 GitHub 조회로 확인했다.
값은 `arn:aws:iam::577638373354:role/heapy-ocr-dev-deployment-role-DeploymentRole-QNu8mI3TAGBx`다.
사용자가 IAM 신뢰 관계의 audience 및 environment:dev subject 일치를 확인했다.
실제 권한 본문 및 OIDC 인증 성공은 아직 별도 확인이 필요하다.
저장소 변수 AWS_DEPLOYMENT_APPROVED는
최종 활성화 시 true로 설정한다. 현재는 미설정이라 자동 배포가 실행되지 않는다.
이 변수는 작업 if 조건에서 사용하므로 환경 변수가 아니라 저장소 변수로 설정한다.
PRODUCTION_DEPLOYMENT_APPROVED는 미설정으로 유지한다.

## 2. AWS 코드 배포 역할 생성

CloudFormation 서울 리전에서 새 스택을 생성한다.
템플릿 파일은 `infra/deployment-role.yaml`, 스택 이름은 `heapy-ocr-dev-deployment-role`이다.
동일 이름 스택이 이미 있다면 중복 생성하지 말고 상태와 출력을 먼저 확인한다.

| 파라미터 | 입력값 |
|---|---|
| GitHubRepository | `Heapy-AI/heapy-ocr-lambda` |
| GitHubEnvironment | `dev` |
| GitHubSubjectPrefix | `repo:Heapy-AI@305710690/heapy-ocr-lambda@1348001285` |
| OidcProviderArn | `arn:aws:iam::577638373354:oidc-provider/token.actions.githubusercontent.com` |
| EcrRepositoryArn | `arn:aws:ecr:ap-northeast-2:577638373354:repository/heapy-ocr-dev-registry-repository-sprmdejyled7` |
| WorkerFunctionName | `heapy-ocr-dev-runtime-Worker-BRv8BzBzvAaB` |
| JanitorFunctionName | `heapy-ocr-dev-runtime-Janitor-FworyPJX1Wbx` |

옵션은 기본값으로 진행하고 마지막 검토에서 IAM 리소스 생성 확인을 선택한다.
이 스택은 IAM 역할과 인라인 정책만 생성하며 Lambda 코드 교체나 새 컴퓨팅 자원을 생성하지 않는다.
CREATE_COMPLETE 후 출력의 DeploymentRoleArn을 전달한다. 비밀 키는 전달하지 않는다.

### 권한 범위

- 기존 ECR 저장소의 이미지 업로드·조회와 ECR 로그인
- 기존 Worker·Janitor 두 함수의 코드 갱신·버전 발행·live 별칭 전환 및 스모크 Invoke
- OIDC audience sts.amazonaws.com 및 위 저장소의 environment:dev subject로 제한
- GitHub dev 환경의 브랜치 제한과 함께 사용한다. 환경 subject 자체에는 브랜치가 포함되지 않는다.
- IAM 변경·CloudFormation 변경·Secrets Manager 직접 조회 권한은 포함하지 않는다.
- 코드 배포 권한은 실행 역할을 통해 비밀을 사용하는 코드를 변경할 수 있는 민감한 권한이다.
  따라서 저장소 쓰기 권한과 dev 환경 규칙을 유지·관리해야 한다.

## 3. 역할 생성 후 순서

배포 준비 검사: 2026-09-08 로컬 테스트 67개 통과(3.42초), Ruff 및 전체 CloudFormation
템플릿 검사 통과. 다음 배포는 기존 개발 Worker·Janitor 코드와 live 별칭을 갱신한다.
이미지 빌드·ECR 저장·Lambda 스모크 비용이 발생할 수 있다. 운영 main은 활성화하지 않는다.

1. DeploymentRoleArn과 신뢰 정책·권한이 템플릿의 대상과 일치하는지 확인한다.
2. dev 환경 변수 AWS_DEPLOY_ROLE_ARN을 추가한다.
3. 기존 서버 비밀과 모델 설정을 확인한다. 합성 OCR 흐름은 성공했지만 실제 비밀값은 출력하지 않는다.
4. 코드·워크플로 검사를 완료하고 최초 자동 배포의 대상 커밋과 롤백 기준 버전을 기록한다.
5. 승인된 시점에 AWS_DEPLOYMENT_APPROVED를 저장소 변수 true로 설정하고 dev 배포를 실행한다.
6. GitHub 로그에서 새 버전 스모크·live 전환을 확인한다. 실패 시 scripts/deploy.py가 이전 별칭 버전 복원을 시도하며 복원 실패는 수동 확인 대상으로 보고한다.

현재 Worker live 버전 1은 EC2 Invoke 출력으로 확인했다. Janitor live 숫자 버전은 아직 조회하지 않았다.
실환경 롤백은 아직 검증하지 않았다. 실제 OCR과 스모크 검증은 서로 구분한다.

## 참조

Reference 및 Reference/rule 폴더는 없다. `백엔드_OCR_Lambda_연동_인계서.md`에 기록된
API·아키텍처·요구사항·DB 기준 대조를 유지하며, `infra/deployment-role.yaml`,
`.github/workflows/test.yml`, `scripts/deploy.py`를 확인했다.

- [GitHub 환경 API](https://docs.github.com/en/rest/deployments/environments)
- [GitHub 배포 브랜치 정책 API](https://docs.github.com/en/rest/deployments/branch-policies)
