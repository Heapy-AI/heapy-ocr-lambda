"""사용자 JWT와 RLS를 사용하는 Supabase Data API 어댑터.

작성자: 김진우
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from threading import RLock
from typing import Any

from heapy_ocr.exceptions import ExternalServiceError, OcrError
from heapy_ocr.models import MasterCheckupItem, ParsedCheckupItem


class SupabaseGateway:
    """service_role 없이 건강검진 마스터 조회와 저장 RPC를 호출한다."""

    def __init__(
        self,
        url: str,
        publishable_key: str,
        timeout_seconds: int,
    ) -> None:
        self.url = url.rstrip("/")
        self.publishable_key = publishable_key
        self.timeout_seconds = timeout_seconds
        self._catalog: tuple[MasterCheckupItem, ...] = ()
        self._catalog_lock = RLock()

    def get_catalog(self, access_token: str) -> tuple[MasterCheckupItem, ...]:
        with self._catalog_lock:
            if self._catalog:
                return self._catalog
            payload = self._request(
                "GET",
                "/rest/v1/master_checkup_item"
                "?select=item_code,item_name,standard_unit&order=item_code.asc",
                access_token,
            )
            if not isinstance(payload, list):
                raise ExternalServiceError("건강검진 항목 마스터 형식이 올바르지 않습니다.")
            self._catalog = tuple(
                MasterCheckupItem(
                    item_code=str(row["item_code"]),
                    item_name=str(row["item_name"]),
                    standard_unit=(
                        str(row["standard_unit"])
                        if row.get("standard_unit") is not None
                        else None
                    ),
                )
                for row in payload
                if row.get("item_code") and row.get("item_name")
            )
            if not self._catalog:
                raise ExternalServiceError("건강검진 항목 마스터가 비어 있습니다.")
            return self._catalog

    def save_checkup(
        self,
        access_token: str,
        measured_at: str,
        items: tuple[ParsedCheckupItem, ...],
    ) -> str:
        payload = self._request(
            "POST",
            "/rest/v1/rpc/create_health_checkup_from_ocr",
            access_token,
            {
                "p_measured_at": measured_at,
                "p_results": [
                    {
                        "item_code": item.item_code,
                        "value": item.value,
                        "status": item.printed_status,
                    }
                    for item in items
                ],
            },
        )
        if not isinstance(payload, str) or not payload:
            raise ExternalServiceError("건강검진 저장 결과 식별자가 없습니다.")
        return payload

    def _request(
        self,
        method: str,
        path: str,
        access_token: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        if not self.url or not self.publishable_key:
            raise ExternalServiceError("Supabase 환경변수가 설정되지 않았습니다.")
        if not access_token:
            raise OcrError("사용자 인증 토큰이 필요합니다.", 401)

        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
        request = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "apikey": self.publishable_key,
                "Authorization": f"Bearer {access_token}",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                response_text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace")
            try:
                error_payload = json.loads(response_text)
            except json.JSONDecodeError:
                error_payload = {}
            message = str(
                error_payload.get("message")
                or error_payload.get("details")
                or "Supabase 요청에 실패했습니다."
            )
            status_code = 401 if exc.code in {401, 403} else 502
            raise OcrError(message, status_code) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ExternalServiceError("Supabase에 연결할 수 없습니다.") from exc

        if not response_text:
            return None
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ExternalServiceError("Supabase 응답 형식이 올바르지 않습니다.") from exc
