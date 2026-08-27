# HEAPY OCR DB 저장 설계

- 작성자: 김진우

## 기존 테이블 사용

OCR 전용 개인 테이블을 추가하지 않고 HEAPY의 기존 건강검진 테이블을 사용합니다.

```text
auth.users.id
  └─ public.users.user_id
       └─ public.health_checkup_records.user_id
            └─ public.health_checkup_results.record_id
                 └─ public.master_checkup_item.item_code
```

## 저장 매핑

| OCR 결과 | DB 컬럼 |
|---|---|
| 로그인 사용자 | `health_checkup_records.user_id` |
| `measured_at` | `health_checkup_records.measured_at` |
| `item_code` | `health_checkup_results.item_code` |
| `value` | `health_checkup_results.value` |
| `printed_status` | `health_checkup_results.status` |

현재 DB에는 기관명, 단위, OCR 신뢰도, OCR 원문 컬럼이 없습니다. 단위는
`master_checkup_item.standard_unit`에서 조회하고, OCR 원문과 신뢰도는 개인 데이터 최소화
원칙에 따라 저장하지 않습니다.

## 저장 RPC

`create_health_checkup_from_ocr(date, jsonb)`는 다음을 한 트랜잭션으로 수행합니다.

1. `auth.uid()` 존재 확인
2. 검진일과 결과 배열 검증
3. 중복·빈 항목 코드 확인
4. 모든 항목 코드가 마스터에 존재하는지 확인
5. 사용자 검진 회차 생성
6. 검진 결과 일괄 생성
7. `record_id` 반환

함수는 `SECURITY INVOKER`이므로 호출 사용자의 권한과 RLS를 그대로 적용합니다.
`PUBLIC`, `anon` 실행 권한은 제거하고 `authenticated`에만 실행 권한을 부여합니다.

## RLS

- 회차 삽입: `auth.uid() = user_id`
- 결과 삽입: 결과가 속한 회차의 `user_id = auth.uid()`
- 마스터 조회: 인증된 사용자 읽기 전용
- `service_role` 키 사용 금지
