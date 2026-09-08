"""OCR 처리 과정에서 사용하는 예외.

작성자: 김진우
"""


class OcrError(Exception):
    """클라이언트에 안전하게 전달할 수 있는 OCR 오류."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ExternalServiceError(OcrError):
    """외부 서비스 호출 실패."""

    def __init__(self, message: str, diagnostic_code=None, http_status=None) -> None:
        super().__init__(message, 503)
        self.diagnostic_code = diagnostic_code
        self.http_status = http_status
