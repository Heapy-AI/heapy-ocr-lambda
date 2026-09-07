# 최초 이미지 업로드 역할 생성 확인

- 작성자: 김진우
- 상태: 템플릿 준비·검사 완료, AWS 역할 생성 승인 대기
- 계정·리전: `577638373354`, `ap-northeast-2`

## 필요한 이유와 범위

Lambda 컨테이너는 먼저 ECR에 이미지가 있어야 생성할 수 있다. 로컬 Docker가 없어
GitHub Actions에서 초기 이미지를 빌드·업로드하도록 업로드 전용 역할을 준비한다.
기존 코드 배포 역할은 Lambda 생성 후 사용할 예정이므로 이번 역할에는 Lambda 권한을 주지 않는다.

CloudFormation 스택 `heapy-ocr-dev-image-push-role`에 `infra/image-push-role.yaml`을 적용한다.
IAM 역할 1개와 인라인 정책 1개가 생성된다. 기존 백엔드 역할·정책은 변경하지 않는다.
역할 이름은 자동 생성하고 출력의 `ImagePushRoleArn`을 사용한다.

| 매개변수 | 입력값 |
|---|---|
| GitHubRepository | `Heapy-AI/heapy-ocr-lambda` |
| GitHubSubjectPrefix | `repo:Heapy-AI@305710690/heapy-ocr-lambda@1348001285` |
| EcrRepositoryName | `heapy-ocr-dev-registry-repository-sprmdejyled7` |

신뢰 정책은 기존 GitHub OIDC 공급자, 대상 sts.amazonaws.com과 위 접두사의
`:ref:refs/heads/dev`만 허용한다. main·PR·다른 저장소는 허용하지 않는다.
권한은 ECR 로그인과 해당 저장소의 레이어 업로드·이미지 등록·조회뿐이다.
ECR 인증 토큰 권한은 AWS 요구에 따라 Resource=*이며 실제 저장소 작업은 단일 ARN에 제한한다.
장기 AWS 키·Secrets Manager 조회·S3 접근·Lambda 배포·IAM 변경·이미지 삭제 권한은 없다.

이번 승인 대상은 역할 생성이다. 이미지 업로드 실행과 GitHub 배포 활성화는 별도 단계다.
이후 업로드 시 ECR 저장 요금과 계정 플랜에 따른 GitHub Actions 실행 사용량이 발생할 수 있다.

## 실제 검증

[Actions 34117450794의 oidc-probe](https://github.com/Heapy-AI/heapy-ocr-lambda/actions/runs/34117450794/job/101727473582)에서
실제 발급값의 sub와 aud만 확인했다. 토큰 원문은 출력하지 않았고 AWS 인증에 사용하지 않았다.

```text
sub=repo:Heapy-AI@305710690/heapy-ocr-lambda@1348001285:ref:refs/heads/dev
aud=sts.amazonaws.com
```

REST 메타데이터의 use_immutable_subject=false만으로 기존 이름 기반 sub를 사용하면 안 된다.
위 실제 발급 결과를 우선한다. 이후 환경 기반 코드 배포 역할에도 확인된 접두사를 전달하며
GitHub dev 환경의 허용 브랜치를 dev로 제한해야 한다.

## 승인 후 진행

CloudFormation → 스택 생성 → 새 리소스 사용(표준) → 템플릿 파일 업로드에서
`C:/Users/jinwo/heapy-ocr-lambda/infra/image-push-role.yaml`을 선택한다.
위 스택명·매개변수를 입력하고 기본 옵션으로 검토한다. IAM 리소스 생성 확인 항목에
동의한 뒤 생성하고 CREATE_COMPLETE 후 출력의 ImagePushRoleArn을 전달한다.

## 참조

- `백엔드_OCR_Lambda_연동_인계서.md` 1·9·12절 및 `infra/image-push-role.yaml`
- API·아키텍처·요구사항·DB 책임 경계는 인계서의 대조 결과를 유지한다. Reference 폴더는 없다.
- [GitHub OIDC 신뢰 정책](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [AWS ECR 업로드 최소 권한](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html)
