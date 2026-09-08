# AWS 합성 PDF 연동 테스트

- 작성자: 김진우
- 상태: 2026-09-08 사용자 제공 EC2 실행 출력으로 합성 PDF 통합 처리 성공 확인.

## 확인한 실행 결과

- jobId: `0ee8ef9c-b44b-4a68-bc99-ca795fc92f73`
- 원본 업로드 성공, OCR `completed`, error=null, pageCount=1
- 조회 항목 수: 4
- purge 응답: `cancelled`, error=null
- 정리 후 조회: 임시 결과 제거 확인
- expiresAt: `2026-09-08T01:37:43.487274+00:00`
- S3 콘솔에서 해당 jobId의 originals 접두사 검색 적용 후에도 객체 없음: 사용자 확인.

아래 스크립트의 실행 결과로 S3·Lambda OCR·결과 조회·purge 흐름을 확인했다.
정리 후 원본 객체 부재는 S3 콘솔에서도 확인했다. OCR 직후와 purge 이후 삭제 시점을
이번 관찰로 구별할 수는 없다. 실제 600초 만료 회수, 한국어 양식 인식 정확도와
백엔드 애플리케이션·모바일 연동은 아직 미검증이다. Gemini 단독 성공 여부는 응답에
엔진 식별 정보가 없어 단정하지 않는다. 완료 이후 이 테스트를 재실행할 필요는 없다.

## 실행 범위

백엔드 EC2 터미널에서 아래 블록 전체를 한 번에 실행한다. 합성 PDF만 전송하며 실제 건강 문서는 사용하지 않는다.
기존 개발 S3·Lambda와 서버 비밀 설정을 사용해 OCR을 실행하므로 Gemini 및 AWS 호출 비용이 발생할 수 있다.
새 자원 생성·IAM 변경·백엔드 코드 수정은 하지 않는다. 600초 TTL은 업로드 준비부터 계산한다.

정상 흐름은 원본 업로드 → 제어 객체 생성 → OCR → 결과 조회 → purge → 결과 제거 확인이다.
중간 실패에도 제어 객체 생성이 성공했다면 purge를 시도한다. 제어 객체 생성 응답이 유실되거나 프로세스가 종료되면
회수 Lambda가 만료된 작업·고아 원본을 회수해야 한다. 정리 오류는 성공으로 처리하지 않는다.
출력에는 상태·오류 코드·항목 수만 표시한다. 테스트 결과를 확인한 후 EC2의 합성 원본을 별도로 제거한다.

## EC2에서 실행

```bash
python3 - <<'PY'
# 합성 PDF만 허용하는 개발 연동 점검. 작성자: 김진우
import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

source = Path('/tmp/heapy-ocr-smoke-ny8q1mtk/source.pdf')
bucket = 'heapy-ocr-dev-runtime-bucket-gaxs20bnat6n'
account = '577638373354'
region = 'ap-northeast-2'
function = 'heapy-ocr-dev-runtime-Worker-BRv8BzBzvAaB'
data = source.read_bytes()
if hashlib.sha256(data).hexdigest() != '014555784ddde09fdfb758d474641335f024b2c64ac876e987a8848c048f313e':
    raise SystemExit('중단: 준비한 합성 PDF가 아닙니다.')

def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')

def aws(*arguments):
    env = dict(os.environ, AWS_PAGER='', AWS_MAX_ATTEMPTS='1')
    result = subprocess.run(
        ['aws', '--region', region, '--output', 'json', *arguments],
        capture_output=True, text=True, env=env, timeout=960)
    if result.returncode:
        # 입력이 합성 데이터이며 AWS CLI 오류만 출력한다. 비밀 조회는 수행하지 않는다.
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout or '{}')

identity = aws('sts', 'get-caller-identity')
prefix = 'arn:aws:sts::' + account + ':assumed-role/heapy-backend-dev-ec2-role/'
if identity.get('Account') != account or not identity.get('Arn', '').startswith(prefix):
    raise SystemExit('중단: 백엔드 EC2 역할이 아닙니다.')

job_id = str(uuid.uuid4())
now = datetime.now(timezone.utc)
request = dict(contractVersion='1.0', jobId=job_id,
               documentType='health_checkup', inputType='pdf',
               createdAt=now.isoformat(), expiresAt=(now + timedelta(seconds=600)).isoformat(),
               source=dict(bucket=bucket, key='originals/' + job_id + '/source',
                           extension='pdf', sizeBytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
state = dict(request=request, fingerprint=hashlib.sha256(encode(request)).hexdigest(), status='pending')
print('jobId:', job_id, flush=True)

with tempfile.TemporaryDirectory(prefix='heapy-ocr-call-') as directory:
    folder = Path(directory)

    def invoke(payload):
        event_file = folder / 'event.json'
        reply_file = folder / 'reply.json'
        event_file.write_bytes(encode(payload))
        meta = aws('lambda', 'invoke', '--function-name', function, '--qualifier', 'live',
                   '--cli-read-timeout', '920', '--cli-binary-format', 'raw-in-base64-out',
                   '--payload', 'fileb://' + str(event_file), str(reply_file))
        if meta.get('StatusCode') != 200 or meta.get('FunctionError'):
            raise RuntimeError('Lambda 호출 실패: ' + json.dumps(meta))
        return json.loads(reply_file.read_text(encoding='utf-8'))

    def operation(name):
        return dict(contractVersion='1.0', operation=name, request=request,
                    reason='cancelled' if name == 'purge' else None)

    created = False
    try:
        aws('s3api', 'put-object', '--bucket', bucket, '--key', request['source']['key'],
            '--expected-bucket-owner', account, '--body', str(source),
            '--if-none-match', '*', '--server-side-encryption', 'AES256',
            '--content-type', 'application/pdf', '--cache-control', 'no-store')
        print('원본 업로드 성공', flush=True)
        state_file = folder / 'state.json'
        state_file.write_bytes(encode(state))
        aws('s3api', 'put-object', '--bucket', bucket, '--key', 'jobs/' + job_id + '.json',
            '--expected-bucket-owner', account, '--body', str(state_file),
            '--if-none-match', '*', '--server-side-encryption', 'AES256',
            '--content-type', 'application/json', '--cache-control', 'no-store')
        created = True
        receipt = invoke(request)
        print('OCR 응답:', json.dumps(receipt, ensure_ascii=False), flush=True)
        if receipt.get('status') != 'completed':
            raise RuntimeError('OCR 미완료: 위 오류 코드를 확인하세요.')
        result = invoke(operation('read'))
        if result.get('status') != 'completed' or not isinstance(result.get('result'), dict):
            raise RuntimeError('결과 조회 실패')
        count = len(result['result'].get('items', []))
        print('조회 항목 수:', count, flush=True)
        if count == 0:
            raise RuntimeError('연결은 완료됐지만 인식 항목이 없어 품질 확인이 필요합니다.')
    finally:
        if created:
            purged = invoke(operation('purge'))
            print('정리 응답:', json.dumps(purged, ensure_ascii=False), flush=True)
            if purged.get('status') not in ('cancelled', 'expired', 'confirmed'):
                raise RuntimeError('정리 실패: 회수 상태를 확인해야 합니다.')
            after = invoke(operation('read'))
            if after.get('status') in ('cancelled', 'confirmed') and after.get('result') is None:
                print('임시 결과 제거 확인', flush=True)
            else:
                raise RuntimeError('정리 후 조회 확인 실패 또는 만료: 별도 점검 필요')
PY
```

## 결과 해석과 남은 검증

- `completed`는 구현상 원본 DeleteObject 성공 후에만 게시된다. 실제 객체 부재의 독립 확인은 별도다.
- 백엔드 역할에는 원본 GetObject·ListBucket 권한이 없어 HeadObject 실패를 삭제 증거로 해석하면 안 된다.
- `임시 결과 제거 확인`은 조회 응답에서 결과 제거를 확인한 것이다. 최소 제어 메타데이터는 재실행 방지용으로 남아 회수기가 제거한다.
- 성공해도 Gemini와 선택적 Vision 중 어느 경로가 결과를 생성했는지 이 응답만으로 단정하지 않는다.
- 일반검진 한국어 양식 인식 품질, 실제 600초 만료, 강제 종료 회수, 원본 객체 부재 확인은 별도 검증이다.
- 실패 출력은 수정 전에 먼저 확인한다. 같은 파일을 무조건 재업로드하거나 반복 실행하지 않는다.

## 참조

Reference 폴더는 없다. `백엔드_OCR_Lambda_연동_인계서.md`의 기준 문서 대조·내부 계약,
`heapy_ocr/contract.py`, `heapy_ocr/worker.py`, `infra/runtime.yaml`의 권한을 참조했다.
