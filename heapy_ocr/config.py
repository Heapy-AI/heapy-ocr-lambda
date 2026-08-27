"""환경변수 기반 애플리케이션 설정.

작성자: 김진우
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value <= 0:
        raise RuntimeError(f"{name}은 1 이상의 정수여야 합니다.")
    return value


@dataclass(frozen=True)
class Settings:
    """Lambda 실행 설정."""

    internal_secret_key: str
    gemini_api_key: str
    gemini_model: str
    supabase_url: str
    supabase_publishable_key: str
    max_image_bytes: int
    external_timeout_seconds: int

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            internal_secret_key=os.environ.get("INTERNAL_SECRET_KEY", "").strip(),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip(),
            supabase_url=os.environ.get("SUPABASE_URL", "").strip().rstrip("/"),
            supabase_publishable_key=(
                os.environ.get("SUPABASE_PUBLISHABLE_KEY")
                or os.environ.get("SUPABASE_ANON_KEY")
                or ""
            ).strip(),
            max_image_bytes=_positive_int("MAX_IMAGE_BYTES", 5 * 1024 * 1024),
            external_timeout_seconds=_positive_int("EXTERNAL_TIMEOUT_SECONDS", 20),
        )
