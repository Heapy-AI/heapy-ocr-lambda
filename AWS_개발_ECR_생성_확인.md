# OCR 개발용 ECR 생성 확인

- 작성자: 김진우
- 상태: 사용자가 생성 후 RepositoryUri 전달. 실제 이미지 업로드·Lambda 배포는 미실행.
- 계정: `577638373354`
- 리전: 서울 `ap-northeast-2`
- 사용자 확인: 기존 OCR용 저장소가 없어 승인 후 CloudFormation 생성 절차 진행
- RepositoryUri: `577638373354.dkr.ecr.ap-northeast-2.amazonaws.com/heapy-ocr-dev-registry-repository-sprmdejyled7`

## 생성 범위

기존 `infra/registry.yaml`로 CloudFormation 스택 `heapy-ocr-dev-registry`를 생성한다.
스택이 비공개 ECR 저장소 1개를 생성하며 저장소 이름은 자동 생성한다.

- 암호화: AES256
- 이미지 태그: 변경 불가
- 기본 이미지 검사: 업로드 시 검사. 기존 레지스트리의 강화 검사 설정은 변경하지 않는다.
- 저장소 정책: 동일 계정·서울 리전 Lambda 서비스의 이미지 읽기 허용
- 스택 삭제·교체 시 저장소 유지. 이미지 자동 삭제 정책은 이번에 추가하지 않는다.
- 출력: 실제 `RepositoryUri`, `RepositoryArn`

이번 범위는 ECR과 위 저장소 정책이다. IAM 역할 생성·백엔드 정책 연결·Lambda 배포는 별도 단계다.
이미지 업로드도 이번 생성과 구분한다. 검진 원본이나 API 키를 ECR에 넣지 않는다.

CloudFormation 콘솔에서 템플릿 파일 업로드 방식을 사용하면 AWS가 템플릿 보관용 S3를
사용하거나 생성할 수 있다. 이는 OCR 원본용 버킷이 아니며 작은 템플릿 저장·요청 비용이
발생할 수 있다. 템플릿에 비밀 값이나 건강 문서는 포함하지 않는다.

## 비용

ECR은 저장량과 외부 전송량에 따라 과금한다. AWS 공식 요금 예시의 저장 단가는
GB당 월 USD 0.10으로, 총 1GB 보관 시 월 약 USD 0.10이다. 실제 이미지 크기·보관량은
업로드 뒤 확인하며 서울 적용 요금·세금·크레딧은 별도 확인한다.
같은 리전의 ECR→Lambda 전송은 무료다. 외부·다른 리전 전송 및 기존 강화 검사 설정은
추가 비용 대상이 될 수 있다. 빈 저장소 생성만으로 Lambda 실행 비용은 발생하지 않는다.

## 승인 후 첫 화면

CloudFormation → 서울 리전 → 스택 생성 → 새 리소스 사용(표준) → 기존 템플릿 선택 →
템플릿 파일 업로드에서 `C:/Users/jinwo/heapy-ocr-lambda/infra/registry.yaml`을 선택한다.
다음 단계에 스택 이름 `heapy-ocr-dev-registry`를 입력한다. 검토 화면에서 생성 범위를
확인한 뒤 제출하고 CREATE_COMPLETE 후 출력 탭의 RepositoryUri를 확인한다.

## 참조

- `백엔드_OCR_Lambda_연동_인계서.md` 9·12절 및 `infra/registry.yaml`
- 인계서 1절의 API·시스템 아키텍처·요구사항·DB 문서와 책임 경계를 유지한다. Reference 폴더는 없다.
- [AWS ECR 요금](https://aws.amazon.com/ecr/pricing/)
- [CloudFormation 콘솔 스택 생성](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-create-stack.html)
