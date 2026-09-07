# OCR 개발용 비밀 생성 확인

- 작성자: 김진우
- 상태: 사용자 콘솔 생성 완료 보고, ARN 형식·계정·리전 일치 확인. 실제 키·접근 권한 미검증.
- 계정: `577638373354`
- 리전: 서울 `ap-northeast-2`
- 사용자 확인: GitHub OIDC 공급자와 대상 확인 완료. 기존 비밀이 없어 아래 개발 비밀을 새로 생성했다고 보고함.
- 전달받은 SecretArn: `arn:aws:secretsmanager:ap-northeast-2:577638373354:secret:heapy/dev/ocr-yHbFSW`

## 이번 생성 범위

| 항목 | 제안 설정 |
|---|---|
| 서비스·수량 | AWS Secrets Manager 비밀 1개 |
| 이름 | `heapy/dev/ocr` |
| 유형 | 다른 유형의 보안 암호 |
| 키 이름 | `GEMINI_API_KEY` |
| 값 | 사용자가 AWS 콘솔에 직접 입력. 대화·Git에 전달하지 않음 |
| 암호화 키 | 기본 `aws/secretsmanager` |
| 자동 교체 | 초기에는 사용하지 않음. Gemini 키 교체 연동은 별도 구성 필요 |
| 다른 리전 복제 | 없음 |

이번에는 비밀만 생성하며 IAM 정책 연결·S3·Lambda 생성·배포는 포함하지 않는다.
선택 Vision 키는 필요할 때 같은 비밀에 추가할 수 있다.

## 비용

AWS 공식 요금 안내는 비밀 1개 월 USD 0.40와 API 호출 10,000회당 USD 0.05를 제시한다.
환율·세금·계정 크레딧 적용 전 기준이며 콘솔의 적용 요금을 최종 확인한다.
이는 키 보관 비용이고 Gemini 사용료 및 이후 Lambda·S3 비용은 별도다.
지원금 200,000원의 적용 여부나 자동 비용 차단은 보장하지 않는다.

## 승인 후 진행

Secrets Manager에서 새 비밀 저장 화면을 열고 위 설정으로 입력한 뒤 검토 화면에서 저장한다.
사용자는 생성 후 비밀 ARN만 전달하며 실제 키는 보내지 않는다.
Gemini 키가 아직 없다면 생성·입력 준비부터 진행한다.

## 참조

- `백엔드_OCR_Lambda_연동_인계서.md` 9·12절: 비밀 이름·권한·최초 배포 경계
- 해당 인계서 1절의 API·아키텍처·요구사항·DB 문서 대조 결과를 유지한다. Reference 폴더는 없다.
- [AWS Secrets Manager 요금](https://aws.amazon.com/secrets-manager/pricing/)
- [AWS 비밀 생성 안내](https://docs.aws.amazon.com/secretsmanager/latest/userguide/create_secret.html)
