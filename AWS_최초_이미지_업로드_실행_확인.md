# 최초 OCR 이미지 업로드 실행 확인

- 작성자: 김진우
- 상태: 사용자 승인 후 최초 이미지 업로드 성공. Lambda 생성·배포는 미실행.
- 계정·리전: `577638373354`, `ap-northeast-2`
- 저장소·브랜치: `Heapy-AI/heapy-ocr-lambda`, `dev`
- ECR: `577638373354.dkr.ecr.ap-northeast-2.amazonaws.com/heapy-ocr-dev-registry-repository-sprmdejyled7`
- 업로드 역할: `arn:aws:iam::577638373354:role/heapy-ocr-dev-image-push-role-ImagePushRole-Jn1OXuDIMRn2`

## 승인받을 작업

기존 `.github/workflows/test.yml`을 dev 대상으로 한 번 수동 실행한다.
`upload_initial_image=true`, `oidc_probe=false`와 위 계정·리전·역할·저장소를 입력한다.
별도의 GitHub 저장소 변수·비밀 값은 설정하지 않는다.

1. 테스트·Ruff·인프라 검사·Lambda Linux 컨테이너의 합성 PDF selftest를 수행한다.
2. 승인된 역할을 OIDC로 인수하여 해당 ECR에 로그인한다. 장기 AWS 키는 저장하지 않는다.
3. 해당 실행의 Git 커밋 SHA 태그가 없으면 이미지를 빌드·합성 검증하고 업로드한다.
4. 같은 SHA가 있으면 해당 digest를 가져와 검증하며 덮어쓰지 않는다.
5. 실제 digest·커밋·저장 크기를 Actions 요약과 인계서에 기록한다.

Lambda 생성·코드 배포·백엔드 변경·IAM 변경·S3 접근·비밀 조회·Gemini 호출은 없다.
업로드 전용 모드에서는 기존 deploy 작업이 실행되지 않도록 조건을 분리했다.
실제 검진 문서·OCR 결과·API 키는 이미지 빌드 대상에서 제외한다.

## 비용

이미지 업로드 후 ECR 저장 비용이 발생한다. 공식 안내의 GB당 월 USD 0.10 기준으로
저장된 총 이미지가 1GB면 월 약 USD 0.10이다. 업로드 후 실제 바이트 크기를 확인한다.
GitHub Actions의 Linux 실행 시간도 계정 플랜·남은 포함 사용량에 따라 과금될 수 있다.
무료 구간·지원금 적용·세금은 별도이며 이번 단계에서 Gemini·Lambda 실행료는 발생하지 않는다.

## 검증

`scripts/initial_image.py`와 최초 업로드용 수동 작업을 작성했다.
잘못된 계정·리전·역할·외부 URL·main 브랜치 차단 및 PDF selftest 실패 시 push 미실행을
합성 테스트로 확인했다. 전체 66개 테스트와 Ruff를 통과했다.
현재 단계에서 실제 ECR 인증·업로드 성공 또는 Lambda 배포 완료를 주장하지 않는다.

## 참조

- `백엔드_OCR_Lambda_연동_인계서.md`의 API·아키텍처·요구사항·DB 대조 및 배포 경계
- `AWS_최초_이미지_업로드_역할_확인.md`, `infra/image-push-role.yaml`
- [ECR 요금](https://aws.amazon.com/ecr/pricing/)
- [ECR 업로드 권한](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html)

현재 프로젝트의 Reference 폴더는 없으며 인계서에 실제 참조 문서를 기록했다.

## 실제 실행 결과

- 실행: [Actions 34119963614](https://github.com/Heapy-AI/heapy-ocr-lambda/actions/runs/34119963614)
- Git 커밋·이미지 태그: `6f6bff11110d868de2c34d891a6af6099260b691`
- digest: `sha256:a1e309a43afa0f72ad36ecd91fdeef336de6649612027c7b39960d95369a0e09`
- ImageUri: `577638373354.dkr.ecr.ap-northeast-2.amazonaws.com/heapy-ocr-dev-registry-repository-sprmdejyled7@sha256:a1e309a43afa0f72ad36ecd91fdeef336de6649612027c7b39960d95369a0e09`
- ECR 보고 저장 크기: `218115720`바이트, 약 218.12MB 또는 208.01MiB
- 테스트·정적 검사·인프라 검사·Lambda Linux 이미지·합성 PDF selftest: 성공
- 실제 OIDC 역할 인수·ECR 로그인·이미지 업로드·등록 digest 조회: 성공
- test·initial-image 작업: success / deploy 작업: skipped
- Gemini·Vision·실제 건강 문서·S3 원본 처리 흐름은 호출하지 않았다.

저장 크기는 이번 이미지에 대한 ECR 보고값이다. 총 청구량은 다른 이미지·공유 레이어·보관 기간에
따라 달라진다. 위 digest를 이후 runtime.yaml의 ImageUri 매개변수로 사용한다.
인계 문서 후속 커밋이 생겨도 실제 업로드 이미지의 Git 커밋은 위 값으로 기록한다.
