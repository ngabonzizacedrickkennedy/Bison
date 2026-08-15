from __future__ import annotations

from typing import Any

import httpx

from model_broker_service.backends.base import (
    BackendModel,
    BackendTimeoutError,
    BackendUnavailableError,
    ModelBackend,
)

BYTES_PER_GB = 1024**3


class OllamaBackend(ModelBackend):
    name = "ollama"
    locality = "local"

    def __init__(self, base_url: str, connect_timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._connect_timeout = connect_timeout_seconds
        self._client = httpx.AsyncClient(base_url=self._base_url)

    async def healthy(self) -> bool:
        try:
            response = await self._client.get("/api/tags", timeout=self._connect_timeout)
        except httpx.HTTPError:
            return False
        return response.status_code == httpx.codes.OK

    async def list_models(self) -> list[BackendModel]:
        payload = await self._request("GET", "/api/tags", None, self._connect_timeout)
        entries = payload.get("models")

        if not isinstance(entries, list):
            return []

        return [self._describe(entry) for entry in entries if isinstance(entry, dict)]

    async def generate(
        self,
        model_id: str,
        prompt: str,
        *,
        structured: bool,
        timeout_seconds: float,
    ) -> str:
        body: dict[str, Any] = {"model": model_id, "prompt": prompt, "stream": False}

        if structured:
            body["format"] = "json"

        payload = await self._request("POST", "/api/generate", body, timeout_seconds)
        response = payload.get("response")

        if not isinstance(response, str):
            raise BackendUnavailableError(self.name, "generate returned no response field")

        return response

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(timeout_seconds, connect=self._connect_timeout)

        try:
            response = await self._client.request(method, path, json=body, timeout=timeout)
        except httpx.TimeoutException as error:
            raise BackendTimeoutError(self.name, f"{path} exceeded {timeout_seconds}s") from error
        except httpx.HTTPError as error:
            raise BackendUnavailableError(
                self.name, f"{path} unreachable at {self._base_url}"
            ) from error

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise BackendUnavailableError(self.name, f"{path} responded {response.status_code}")

        parsed: Any = response.json()

        if not isinstance(parsed, dict):
            raise BackendUnavailableError(self.name, f"{path} returned a non-object body")

        return parsed

    @staticmethod
    def _describe(entry: dict[str, Any]) -> BackendModel:
        size = entry.get("size")

        return BackendModel(
            model_id=str(entry.get("name", "")),
            provider="ollama",
            locality="local",
            size_gb=round(size / BYTES_PER_GB, 2) if isinstance(size, int | float) else None,
            context_window=None,
        )
