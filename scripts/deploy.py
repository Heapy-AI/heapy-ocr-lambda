"""이미지 버전 검증 후 별칭 전환과 실패 롤백. 작성자: 김진우."""

import json
import os

import boto3
from botocore.config import Config


def smoke(client, name, qualifier):
    result = client.invoke(
        FunctionName=name,
        Qualifier=qualifier,
        InvocationType="RequestResponse",
        Payload=json.dumps({"contractVersion": "1.0", "operation": "selftest"}),
    )
    payload = json.loads(result["Payload"].read())
    if result.get("FunctionError") or payload.get("status") != "ok":
        raise RuntimeError("런타임 스모크 테스트 실패")


def deploy(client, names, image_uri, revision):
    old = {
        name: client.get_alias(FunctionName=name, Name="live")["FunctionVersion"] for name in names
    }
    promoted = []
    try:
        for name in names:
            current = client.get_function_configuration(FunctionName=name)
            client.update_function_code(
                FunctionName=name,
                ImageUri=image_uri,
                RevisionId=current["RevisionId"],
                Publish=False,
            )
            client.get_waiter("function_updated_v2").wait(FunctionName=name)
            version = client.publish_version(FunctionName=name, Description=revision)["Version"]
            client.get_waiter("function_active_v2").wait(FunctionName=name, Qualifier=version)
            smoke(client, name, version)
            alias = client.get_alias(FunctionName=name, Name="live")
            # 네트워크 응답 유실도 롤백 대상에 포함한다.
            promoted.append(name)
            client.update_alias(
                FunctionName=name,
                Name="live",
                FunctionVersion=version,
                RevisionId=alias["RevisionId"],
            )
            smoke(client, name, "live")
            print(f"함수={name} 버전={version} 커밋={revision}")
    except BaseException:
        failed = []
        for name in reversed(promoted):
            try:
                client.update_alias(FunctionName=name, Name="live", FunctionVersion=old[name])
                smoke(client, name, "live")
            except Exception:
                failed.append(name)
        if failed:
            raise RuntimeError("롤백 수동 확인 필요: " + ",".join(failed)) from None
        raise


if __name__ == "__main__":
    client = boto3.client("lambda", config=Config(read_timeout=120, connect_timeout=5))
    deploy(
        client,
        [os.environ["JANITOR_FUNCTION_NAME"], os.environ["WORKER_FUNCTION_NAME"]],
        os.environ["IMAGE_URI"],
        os.environ["GITHUB_SHA"],
    )
