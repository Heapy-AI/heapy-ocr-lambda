# 백엔드 OCR 정책 연결 확인

- 작성자: 김진우
- 작성일: 2026-09-08
- 상태: 사용자 정책 연결 완료 보고 및 Lambda selftest 성공 응답 확인

2026-09-08 사용자가 정책 연결 완료를 보고했고, 안내한 Lambda 테스트 응답
`{"contractVersion":"1.0","status":"ok","pageCount":2}`를 전달했다.
합성 PDF 런타임 검증은 성공했다. 이어 사용자가 EC2에서 확인한 STS ARN은
`arn:aws:sts::577638373354:assumed-role/heapy-backend-dev-ec2-role/i-055b8632e5b93fd96`이다.
같은 EC2에서 live 별칭 selftest를 호출해 StatusCode=200, ExecutedVersion=1,
FunctionError 없음과 위 성공 페이로드를 확인했다. 백엔드 역할의 실제 Lambda 호출은 검증됐다.
S3·Gemini 연동, 원본 삭제·결과 만료는 후속 통합 검증 대상이다.

## 대상과 변경

기존 역할 `heapy-backend-dev-ec2-role`에 다음 관리 정책 1개를 추가 연결한다.

```text
arn:aws:iam::577638373354:policy/heapy-ocr-dev-runtime-BackendPolicy-18wXVpmKiwVJ
```

대상 역할 ARN은 `arn:aws:iam::577638373354:role/heapy-backend-dev-ec2-role`이다.
사용자가 제공한 CloudFormation 출력 화면에서 정책을 확인했다. 콘솔에서는 출력의
BackendPolicyArn과 선택할 정책 ARN이 정확히 일치하는지 확인한 뒤 연결한다.

템플릿이 생성하는 권한은 다음과 같다. 기존 SSM·ECR 정책은 유지한다.

| 권한 | 대상 |
|---|---|
| lambda:InvokeFunction | `arn:aws:lambda:ap-northeast-2:577638373354:function:heapy-ocr-dev-runtime-Worker-BRv8BzBzvAaB:live` |
| s3:PutObject | `arn:aws:s3:::heapy-ocr-dev-runtime-bucket-gaxs20bnat6n/originals/*` |
| s3:PutObject, s3:GetObject | `arn:aws:s3:::heapy-ocr-dev-runtime-bucket-gaxs20bnat6n/jobs/*` |

업무 DB·Secrets Manager·다른 버킷 접근 권한은 추가하지 않는다. 원본 삭제와 purge는
Lambda 책임이다. 기존 백엔드 재시작·코드 변경은 이번 연결 범위가 아니다.
IAM 권한 경계·조직 정책에 따라 실제 호출이 제한될 수 있으므로 연결 후 검증한다.

## 승인 후 콘솔 순서

IAM → 역할 → heapy-backend-dev-ec2-role → 권한 → 권한 추가 → 정책 연결에서
`heapy-ocr-dev-runtime-BackendPolicy-`로 검색하고 CloudFormation 출력 ARN과 대조한다.
위 정책 1개만 선택하여 연결한다. 기존 두 정책을 제거하거나 교체하지 않는다.

## 다음 검증

Lambda의 Worker 함수 live 별칭에 아래 합성 selftest를 실행한다. 테스트는 PDF 네이티브
의존성만 확인하며 S3·Gemini·비밀 조회를 수행하지 않는다. 실제 OCR 성공과 구분한다.

```json
{"contractVersion":"1.0","operation":"selftest"}
```

예상 결과는 contractVersion=1.0, status=ok, pageCount=2다. 이후 합성 문서의 실제
업로드→Invoke→read→purge와 원본 삭제·만료 차단을 별도 검증한다.

## 참조

- `infra/runtime.yaml`의 BackendPolicy 및 `백엔드_OCR_Lambda_연동_인계서.md` 1·9절
- 인계서의 API·아키텍처·요구사항·DB 대조와 책임 경계를 유지한다. Reference 폴더는 없다.
- [AWS 역할에 정책 연결](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_update-role-permissions.html)
