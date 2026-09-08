# OCR 외부 오류 진단 보완

- 작성자: 김진우
- 배경: jobId 37b92d76-ce34-499b-8b68-d8c1236257b9가 EXTERNAL_SERVICE_FAILED로 실패했다.
- 약 63초 실패는 시간 초과 가능성을 시사하지만 기존 로그로 원인을 확정할 수 없다.

## 변경

Gemini 건강검진·복약 및 Vision 호출을 진단한다. 자식 프로세스는 허용된 메타데이터만
최대 32KiB의 전용 임시 파일에 기록한다. 부모 Worker가 값을 다시 검증해 CloudWatch로
전달하며 작업 임시 디렉터리 정리 시 진단 파일도 제거한다. 기존 자식 stdout·stderr와
일반 로그 차단은 유지한다. 진단을 S3 결과나 공개 응답에 추가하지 않는다.

예시(형식 설명용 합성 로그):

```text
OCR_EXTERNAL_CALL jobId=<작업 UUID> provider=gemini callIndex=1 code=TIMEOUT httpStatus=None durationMs=60001
```

| 코드 | 의미 |
|---|---|
| TIMEOUT | 소켓·연결 시간 초과 또는 HTTP 408/504 |
| AUTH_FAILED | HTTP 401/403 또는 Vision 인증·권한 오류 |
| RATE_LIMITED | HTTP 429 또는 Vision 할당량 오류 |
| RESPONSE_FORMAT | JSON·문자 인코딩·구조화 응답 형식 오류 |
| CONNECTION_ERROR / TLS_ERROR | 연결 또는 TLS 장애 |
| SERVER_ERROR / HTTP_ERROR | 외부 서버 장애 또는 그 밖의 HTTP 오류 |
| CONFIGURATION_REQUIRED | API 키 미설정 |
| EMPTY_RESULT | Vision 인식 텍스트 없음 |
| OK | 해당 외부 처리 단계 성공 |
| UNEXPECTED_ERROR | 위 유형으로 분류하지 못한 내부 예외 |

HTTP 응답을 받지 못하면 상태는 None이다. 소요 시간은 호출 준비·전송·파싱을 포함한 단조 시계 측정이다.
callIndex는 작업 내 진단 호출 순번이며 자동 재시도 횟수를 뜻하지 않는다. 재시도 정책은 추가하지 않았다.
Gemini 실패 후 fallback 성공도 각 호출의 진단을 남긴다. 원문·URL·헤더·API 키·응답 본문·예외
메시지를 기록하지 않으며, 외부 HTTP 오류 메시지에서도 서버 응답 본문을 제거했다.

## 검증 및 재검증

로컬 테스트 85개 통과. 직접·중첩 시간 초과, 인증·한도·HTTP 오류, 잘못된 JSON·인코딩·스키마,
fallback 진단 보존, 자식 프로세스 실패 후 부모 전달, 민감정보 차단·파일 크기 제한을 검증했다.
Ruff 및 인프라 검사도 통과했다. 실행 로그의 시간 초과가 확인되기 전에는 60초 제한과 페이지 묶음을 변경하지 않는다.

배포 완료 후 사용자가 앱에서 같은 PDF를 한 번 재업로드한다. 이전 원본은 삭제됐으므로
기존 jobId로 재실행하지 않는다. 실패하면 새 jobId의 OCR_EXTERNAL_CALL과 OCR_FAILURE 행만 공유한다.
성공하면 인식·검수·최종 저장까지 앱에서 확인한다. DB 저장은 백엔드 책임이며 OCR 저장소에서
업무 DB를 직접 수정하거나 실제 건강 문서를 별도 외부 전송하지 않는다.

## 참조

Reference 및 Reference/rule 폴더는 없다. 백엔드 API 명세·검토확정결과, 시스템 아키텍처,
요구사항 2개 및 DB 개발기준서·전체설계·물리설계·ERD·마이그레이션 md의 책임 경계를
`백엔드_OCR_Lambda_연동_인계서.md`와 대조했다. 코드 참조는 gemini.py, google_vision.py,
medication.py, processor.py, worker.py다. 공개 API 및 DB 계약은 변경하지 않았다.
