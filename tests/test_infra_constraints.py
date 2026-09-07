"""정적 검사에서 누락된 AWS IAM 설명 문자 제약 회귀 검증. 작성자: 김진우."""

import re
from pathlib import Path

import pytest
from cfnlint.decode import decode


@pytest.mark.parametrize("path", sorted(Path("infra").glob("*.yaml")), ids=lambda p: p.name)
def test_iam_role_description_uses_allowed_characters(path):
    template, errors = decode(str(path))
    assert not errors
    for name, resource in template.get("Resources", {}).items():
        if resource["Type"] != "AWS::IAM::Role":
            continue
        description = resource.get("Properties", {}).get("Description", "")
        if isinstance(description, dict):
            description = description["Fn::Sub"]
        assert isinstance(description, str), name
        # 현재 치환 매개변수는 영문 저장소·환경명으로 제한돼 있다.
        assert re.fullmatch(r"[\u0009\u000A\u000D\u0020-\u007E\u00A1-\u00FF]*", description), name
        assert len(description) <= 1000, name
