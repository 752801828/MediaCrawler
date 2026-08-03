from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from typing import Any

import requests

from creator_ops.config import FeishuSettings


class FeishuError(RuntimeError):
    """Base error for sanitized Feishu failures."""


class FeishuPermissionError(FeishuError):
    """The application cannot access a requested Feishu resource."""


class FeishuSchemaError(FeishuError):
    """A Feishu table, view, or field does not match configuration."""


class FeishuUnavailableError(FeishuError):
    """A transient Feishu error exhausted its retries."""


class FeishuClient:
    BASE_URL = "https://open.feishu.cn/open-apis"
    MAX_ATTEMPTS = 4

    def __init__(
        self,
        settings: FeishuSettings,
        *,
        session: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self._access_token = ""
        self._access_token_expires_at = 0.0

    def iter_records(
        self,
        app_token: str,
        table_id: str,
        view_id: str = "",
        *,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": page_size}
            if view_id:
                params["view_id"] = view_id
            if page_token:
                params["page_token"] = page_token
            payload = self._authorized_request(
                "GET",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                params=params,
            )
            data = payload.get("data") or {}
            records.extend(data.get("items") or [])
            if not data.get("has_more"):
                return records
            page_token = str(data.get("page_token") or "")
            if not page_token:
                raise FeishuSchemaError("Feishu pagination omitted page_token")

    def query_records(
        self,
        app_token: str,
        table_id: str,
        *,
        filter_formula: str,
        field_names: Iterable[str] = (),
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token = ""
        selected_fields = list(field_names)
        while True:
            params: dict[str, Any] = {
                "page_size": page_size,
                "filter": filter_formula,
            }
            if selected_fields:
                params["field_names"] = json.dumps(
                    selected_fields,
                    ensure_ascii=False,
                )
            if page_token:
                params["page_token"] = page_token
            payload = self._authorized_request(
                "GET",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                params=params,
            )
            data = payload.get("data") or {}
            records.extend(data.get("items") or [])
            if not data.get("has_more"):
                return records
            page_token = str(data.get("page_token") or "")
            if not page_token:
                raise FeishuSchemaError(
                    "Feishu pagination omitted page_token"
                )

    def batch_create_records(
        self,
        app_token: str,
        table_id: str,
        fields: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows = list(fields)
        responses: list[dict[str, Any]] = []
        for start in range(0, len(rows), 500):
            chunk = rows[start : start + 500]
            responses.append(
                self._authorized_request(
                    "POST",
                    f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
                    json={"records": [{"fields": item} for item in chunk]},
                )
            )
        return responses

    def batch_update_records(
        self,
        app_token: str,
        table_id: str,
        records: Iterable[tuple[str, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        rows = list(records)
        responses: list[dict[str, Any]] = []
        for start in range(0, len(rows), 500):
            chunk = rows[start : start + 500]
            responses.append(
                self._authorized_request(
                    "POST",
                    f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update",
                    json={
                        "records": [
                            {"record_id": record_id, "fields": fields}
                            for record_id, fields in chunk
                        ]
                    },
                )
            )
        return responses

    def _authorized_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        token = self._tenant_access_token()
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {token}"
        headers["Content-Type"] = "application/json; charset=utf-8"
        return self._request_json(method, f"{self.BASE_URL}{path}", headers=headers, **kwargs)

    def _tenant_access_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._access_token_expires_at:
            return self._access_token
        payload = self._request_json(
            "POST",
            f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.settings.app_id,
                "app_secret": self.settings.app_secret,
            },
        )
        token = str(payload.get("tenant_access_token") or "")
        if not token:
            raise FeishuSchemaError("Feishu token response omitted tenant_access_token")
        expires_in = int(payload.get("expire") or 7200)
        self._access_token = token
        self._access_token_expires_at = now + max(1, expires_in - 60)
        return token

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("timeout", 10)
        last_reason = "unknown transient error"
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                last_reason = type(exc).__name__
                if attempt + 1 == self.MAX_ATTEMPTS:
                    break
                self.sleeper(float(2**attempt))
                continue

            status = int(response.status_code)
            if status in (401, 403):
                raise FeishuPermissionError(
                    f"Feishu permission denied (HTTP {status})"
                )
            if status == 429 or status >= 500:
                last_reason = f"HTTP {status}"
                if attempt + 1 == self.MAX_ATTEMPTS:
                    break
                self.sleeper(float(2**attempt))
                continue
            if status >= 400:
                raise FeishuSchemaError(f"Feishu request rejected (HTTP {status})")

            try:
                payload = response.json()
            except ValueError as exc:
                raise FeishuSchemaError("Feishu returned invalid JSON") from exc
            code = int(payload.get("code") or 0)
            if code == 0:
                return payload
            if code in {99991663, 99991664, 99991668, 99991672}:
                raise FeishuPermissionError(f"Feishu permission denied (code {code})")
            if code in {99991400, 99991401}:
                last_reason = f"code {code}"
                if attempt + 1 == self.MAX_ATTEMPTS:
                    break
                self.sleeper(float(2**attempt))
                continue
            raise FeishuSchemaError(f"Feishu schema request failed (code {code})")

        raise FeishuUnavailableError(
            f"Feishu unavailable after {self.MAX_ATTEMPTS} attempts ({last_reason})"
        )
