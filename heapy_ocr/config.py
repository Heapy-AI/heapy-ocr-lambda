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


def _bounded_int(name: str, default: int, maximum: int) -> int:
    value = _positive_int(name, default)
    if value > maximum:
        raise RuntimeError(f"{name}은 {maximum} 이하의 정수여야 합니다.")
    return value


@dataclass(frozen=True)
class Settings:
    """Lambda 실행 설정."""

    google_vision_api_key: str
    gemini_api_key: str
    gemini_model: str
    max_image_bytes: int
    external_timeout_seconds: int
    gemini_timeout_seconds: int
    gemini_pages_per_request: int

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            google_vision_api_key=os.environ.get(
                "GOOGLE_VISION_API_KEY", ""
            ).strip(),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip(),
            max_image_bytes=_positive_int("MAX_IMAGE_BYTES", 5 * 1024 * 1024),
            external_timeout_seconds=_positive_int("EXTERNAL_TIMEOUT_SECONDS", 20),
            gemini_timeout_seconds=_positive_int("GEMINI_TIMEOUT_SECONDS", 60),
            gemini_pages_per_request=_bounded_int(
                "GEMINI_PAGES_PER_REQUEST",
                1,
                5,
            ),
        )
