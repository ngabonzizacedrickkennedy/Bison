from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from model_broker_service.backends.base import (
    BackendModel,
    BackendTimeoutError,
    BackendUnavailableError,
    ModelBackend,
    PullProgress,
)
from model_broker_service.catalog import CatalogIndex


class OpenRouterBackend(ModelBackend):
    name = "openrouter"
    locality = "remote"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        connect_timeout_seconds: float,
        catalog: CatalogIndex,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._connect_timeout = connect_timeout_seconds
        self._catalog = catalog
        self._client = httpx.AsyncClient(base_url=self._base_url)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def healthy(self) -> bool:
        if not self._api_key:
            return False

        try:
            response = await self._client.get(
                "/api/v1/auth/key",
                headers=self._headers,
                timeout=self._connect_timeout,
            )
        except httpx.HTTPError:
            return False

        return response.status_code == httpx.codes.OK

    async def list_models(self) -> list[BackendModel]:
        self._require_key()

        return [
            BackendModel(
                model_id=record.model_id,
                provider=self.name,
                locality="remote",
                size_gb=None,
                context_window=record.context_window,
            )
            for record in self._catalog.records_for(self.name)
        ]

    async def generate(
        self,
        model_id: str,
        prompt: str,
        *,
        structured: bool,
        timeout_seconds: float,
    ) -> str:
        self._require_key()

        body: dict[str, Any] = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }

        if structured:
            body["response_format"] = {"type": "json_object"}

        payload = await self._post("/api/v1/chat/completions", body, timeout_seconds)

        return self._content(payload)

    def pull(self, model_id: str) -> AsyncIterator[PullProgress]:
        raise BackendUnavailableError(self.name, f"{model_id} is remote and cannot be pulled")

    async def close(self) -> None:
        await self._client.aclose()

    def _require_key(self) -> None:
        if not self._api_key:
            raise BackendUnavailableError(self.name, "no API key configured")

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(timeout_seconds, connect=self._connect_timeout)

        try:
            response = await self._client.post(
                path, json=body, headers=self._headers, timeout=timeout
            )
        except httpx.TimeoutException as error:
            raise BackendTimeoutError(self.name, f"{path} exceeded {timeout_seconds}s") from error
        except httpx.HTTPError as error:
            raise BackendUnavailableError(
                self.name, f"{path} unreachable at {self._base_url}"
            ) from error

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise BackendUnavailableError(
                self.name,
                f"{path} responded {response.status_code}: {self._reason(response)}",
            )

        parsed: Any = response.json()

        if not isinstance(parsed, dict):
            raise BackendUnavailableError(self.name, f"{path} returned a non-object body")

        return parsed

    def _content(self, payload: dict[str, Any]) -> str:
        failure = payload.get("error")

        if isinstance(failure, dict):
            detail = failure.get("message")
            raise BackendUnavailableError(
                self.name, detail if isinstance(detail, str) else "upstream error"
            )

        choices = payload.get("choices")

        if not isinstance(choices, list) or not choices:
            raise BackendUnavailableError(self.name, "chat completion returned no choices")

        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None

        if not isinstance(content, str):
            raise BackendUnavailableError(self.name, "chat completion returned no content")

        return content

    @staticmethod
    def _reason(response: httpx.Response) -> str:
        try:
            payload: Any = response.json()
        except ValueError:
            return response.text[:200]

        failure = payload.get("error") if isinstance(payload, dict) else None
        detail = failure.get("message") if isinstance(failure, dict) else None

        return detail if isinstance(detail, str) else response.text[:200]
