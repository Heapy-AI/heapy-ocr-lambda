# 개발 OCR 런타임 생성 안내

- 작성자: 김진우
- 상태: 사용자 진행 요청·정책 확정, 동시 실행 한도 사전 확인 중. 런타임 미생성.
- 계정·리전: `577638373354`, 서울 `ap-northeast-2`
- 스택 이름: `heapy-ocr-dev-runtime`
- 템플릿: `C:/Users/jinwo/heapy-ocr-lambda/infra/runtime.yaml`

## 생성 구성과 비용 항목

- 비공개 SSE-S3 임시 버킷 1개: 원본 업로드·작업 제어·검수 결과에 사용.
- OCR Lambda 1개: x86_64, 메모리 2GiB, 최대 실행 900초, 예약 동시성 2.
  애플리케이션은 작업 만료와 종료 여유 시간을 우선하므로 600초 만료 이후 OCR을 계속하지 않는다.
- 회수 Lambda 1개: 256MiB, 최대 실행 300초, 예약 동시성 1, 1분마다 실행.
- Lambda 실행 역할 2개, 백엔드 추가용 관리 정책 1개, live 별칭·버전, EventBridge 일정·호출 권한.
- 7일 보존 로그 그룹 2개, 오류 경보 3개, 처리 실패 사용자 지표 1개.

주요 과금은 OCR 실행 시간·요청, 회수기의 반복 실행, S3 저장·요청, CloudWatch 로그·지표·경보다.
기존 ECR·Secrets Manager 비용과 이후 Gemini 호출 비용은 별도다. 회수기는 문서가 없어도
일정에 따라 실행한다. 30일이면 일정 약 43,200회이고, 1회 평균 1초라고 가정하면
0.25GiB × 43,200초의 실행량이다. 실제 실행 시간·재시도·요금·크레딧에 따라 비용은 달라진다.
예약 동시성 자체에는 추가 요금이 없지만 누적 비용을 제한하는 예산 상한은 아니다.
현재 단계에 EC2·NAT Gateway·API Gateway·프로비저닝된 동시성은 없다.

경보는 생성되지만 알림 수신자 연결은 아직 미정이다. 초기 합성 검증 전 CloudWatch를 직접
확인하고 실제 사용자 문서를 받기 전에 경보 수신 경로와 백엔드 연동을 완료해야 한다.
템플릿은 백엔드 역할에 정책을 자동 연결하지 않으므로 기존 SSM·ECR 권한을 변경하지 않는다.

## 확정 매개변수

| 항목 | 입력값 |
|---|---|
| Environment | `dev` |
| MaxUploadBytes | `20000000` |
| MaxResultTtlSeconds | `600` |
| GeminiModel | `gemini-2.5-flash-lite` |
| BackendRoleArn | `arn:aws:iam::577638373354:role/heapy-backend-dev-ec2-role` |
| SecretArn | `arn:aws:secretsmanager:ap-northeast-2:577638373354:secret:heapy/dev/ocr-yHbFSW` |

ImageUri는 이미 실제 업로드·합성 검증을 마친 다음 digest를 사용한다.

```text
577638373354.dkr.ecr.ap-northeast-2.amazonaws.com/heapy-ocr-dev-registry-repository-sprmdejyled7@sha256:a1e309a43afa0f72ad36ecd91fdeef336de6649612027c7b39960d95369a0e09
```

이번 변경은 테스트·문서뿐이다. 실행 코드에 한도·모델을 하드코딩하지 않으며 위 환경변수로
적용하므로 기존 검증 이미지의 재빌드·재업로드는 필요하지 않다.

## 데이터 삭제 계약

원본은 결과 생성 직후 삭제한다. 실패·취소도 정리하며 원본 삭제 실패 시 결과를 공개하지 않는다.
검수 결과의 유효기간은 작업 생성부터 600초로, 처리 시간도 포함한다. 확정·이탈 purge가
먼저 오면 즉시 제거하고 만료 이후 read는 거부한다. 회수기의 다음 실행·스캔 시간이 추가될 수
있으며 장애 시 물리 삭제 마감을 보장하지 않는다. S3 Lifecycle 2일은 보조 회수다.
신규 버킷에 버전 관리·복제·Object Lock을 설정하지 않으며 조직의 보안·백업 정책은 해제하지 않는다.

## 생성 전 한도 확인

AWS는 예약되지 않은 동시 실행을 최소 100개 남겨야 하므로 현재 템플릿의 2+1 예약에는
UnreservedConcurrentExecutions가 103 이상 필요하다. 기존 함수의 예약 상황을 포함한
실제 값을 확인하기 전에 제출하지 않는다. 부족하면 한도 증가 또는 제한 구성을 검토한다.

AWS 콘솔 CloudShell에서 다음 읽기 전용 명령을 사용한다.

```sh
aws lambda get-account-settings --region ap-northeast-2 --query 'AccountLimit.{Concurrent:ConcurrentExecutions,Unreserved:UnreservedConcurrentExecutions}'
```

## 한도 확인 후 콘솔 순서

CloudFormation에서 새 리소스 사용(표준)으로 runtime.yaml을 업로드하고 위 스택명·매개변수를
입력한다. 옵션은 기본값, IAM 역할 선택은 비워두고 검토 화면에서 IAM 생성 확인 후 제출한다.
CREATE_COMPLETE가 되면 출력 탭의 OcrBucket, WorkerFunctionName, WorkerAliasArn,
JanitorFunctionName, WorkerRoleArn, BackendPolicyArn을 확인한다. ImagePushRoleArn은
런타임 생성·호출 권한이 없으므로 이 단계는 사용자의 승인된 관리 콘솔에서 수행한다.

## 검증·참조

- 600초 경계의 read 차단, 601초 요청 거부, 결과 게시 전 원본 삭제를 합성 테스트로 확인했다.
- 전체 테스트 67개·Ruff·runtime.yaml 검사가 통과했다. 실제 런타임 배포·OCR는 아직 미검증이다.
- `백엔드_OCR_Lambda_연동_인계서.md` 1절의 API·아키텍처·요구사항·DB 대조를 유지한다. Reference는 없다.
- [Lambda 예약 동시 실행 제약](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html)
- [Lambda 요금](https://aws.amazon.com/lambda/pricing/)
- [Gemini 2.5 Flash-Lite 모델](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite)
