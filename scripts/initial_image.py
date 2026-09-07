"""승인된 최초 ECR 이미지 업로드와 합성 런타임 검증. 작성자: 김진우."""

import os
import re
import subprocess
from pathlib import Path

import boto3


def validate_target(env):
    account = env["AWS_ACCOUNT_ID"]
    region = env["AWS_REGION"]
    uri = env["ECR_REPOSITORY_URI"]
    role = env["IMAGE_PUSH_ROLE_ARN"]
    if not re.fullmatch(r"\d{12}", account) or not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", region):
        raise ValueError("계정·리전 형식 오류")
    prefix = f"{account}.dkr.ecr.{region}.amazonaws.com/"
    if not uri.startswith(prefix):
        raise ValueError("저장소의 계정·리전 불일치")
    repository = uri[len(prefix):]
    if not re.fullmatch(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", repository):
        raise ValueError("저장소 이름 형식 오류")
    if not re.fullmatch(rf"arn:aws:iam::{account}:role/[A-Za-z0-9_+=,.@/-]+", role):
        raise ValueError("역할의 계정·형식 불일치")
    if env["GITHUB_REF"] != "refs/heads/dev":
        raise ValueError("최초 업로드는 dev에서만 허용")
    if not re.fullmatch(r"[0-9a-f]{40}", env["GITHUB_SHA"]):
        raise ValueError("커밋 식별값 형식 오류")
    return repository


def upload(env):
    repository = validate_target(env)
    client = boto3.client("ecr", region_name=env["AWS_REGION"])
    uri, commit = env["ECR_REPOSITORY_URI"], env["GITHUB_SHA"]
    query = {"repositoryName": repository, "imageIds": [{"imageTag": commit}]}
    try:
        details = client.describe_images(**query)["imageDetails"][0]
    except client.exceptions.ImageNotFoundException:
        image = f"{uri}:{commit}"
        subprocess.run([
            "docker", "build", "--platform", "linux/amd64", "--provenance=false", "-t", image, "."
        ], check=True)
        smoke(image)
        subprocess.run(["docker", "push", image], check=True)
        details = client.describe_images(**query)["imageDetails"][0]
    else:
        image = f"{uri}@{details['imageDigest']}"
        subprocess.run(["docker", "pull", image], check=True)
        smoke(image)
    digest = details["imageDigest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("이미지 digest 형식 오류")
    report = (
        f"## 최초 OCR 이미지 확인\n\n- 커밋: `{commit}`\n"
        f"- 이미지: `{uri}@{digest}`\n- 저장 크기: {details.get('imageSizeInBytes')} 바이트\n"
        "- 네트워크 차단 합성 PDF selftest 통과\n- Lambda 생성·배포 및 Gemini 호출 없음\n"
    )
    print(report)
    if env.get("GITHUB_STEP_SUMMARY"):
        with Path(env["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as output:
            output.write(report)


def smoke(image):
    subprocess.run([
        "docker", "run", "--rm", "--network", "none", "--entrypoint", "python",
        image, "-m", "heapy_ocr.selftest",
    ], check=True)


if __name__ == "__main__":
    import sys

    if "--validate-only" in sys.argv:
        validate_target(os.environ)
    else:
        upload(os.environ)
