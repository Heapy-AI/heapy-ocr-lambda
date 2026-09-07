"""최초 이미지 업로드 대상과 실패 경계 검증. 작성자: 김진우."""

from unittest.mock import Mock

import pytest

from scripts.initial_image import upload, validate_target


def target():
    return {
        "AWS_ACCOUNT_ID": "123456789012", "AWS_REGION": "ap-northeast-2",
        "ECR_REPOSITORY_URI": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/synthetic",
        "IMAGE_PUSH_ROLE_ARN": "arn:aws:iam::123456789012:role/synthetic",
        "GITHUB_REF": "refs/heads/dev", "GITHUB_SHA": "a" * 40,
    }


@pytest.mark.parametrize("key,value", [
    ("AWS_ACCOUNT_ID", "999999999999"), ("AWS_REGION", "us-east-1"),
    ("GITHUB_REF", "refs/heads/main"), ("ECR_REPOSITORY_URI", "https://outside.invalid/x"),
    ("IMAGE_PUSH_ROLE_ARN", "arn:aws:iam::999999999999:role/synthetic"),
])
def test_wrong_upload_target_rejected(key, value):
    env = target()
    env[key] = value
    with pytest.raises(ValueError):
        validate_target(env)


def test_smoke_failure_does_not_push(monkeypatch):
    class MissingImage(Exception):
        pass

    client = Mock()
    client.exceptions.ImageNotFoundException = MissingImage
    client.describe_images.side_effect = MissingImage
    monkeypatch.setattr("scripts.initial_image.boto3.client", lambda *a, **k: client)
    run = Mock(side_effect=[None, RuntimeError("합성 검증 실패")])
    monkeypatch.setattr("scripts.initial_image.subprocess.run", run)
    with pytest.raises(RuntimeError):
        upload(target())
    assert len(run.call_args_list) == 2
    assert all("push" not in call.args[0] for call in run.call_args_list)
