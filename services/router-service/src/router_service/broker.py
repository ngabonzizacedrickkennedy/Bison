from __future__ import annotations

from typing import Any

import httpx

BINDING_ROLE = "mediator"


class BrokerError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"model-broker responded {status}: {detail}")
        self.status = status
        self.detail = detail


class BrokerUnreachableError(RuntimeError):
    def __init__(self, base_url: str) -> None:
        super().__init__(f"model-broker unreachable at {base_url}")


class BrokerClient:
    def __init__(self, base_url: str, timeout_seconds: float, connect_timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)
        self._connect_timeout = connect_timeout
        self._client = httpx.AsyncClient(base_url=self._base_url)

    async def close(self) -> None:
        await self._client.aclose()

    async def binding(self, project_id: str) -> str:
        try:
            response = await self._client.get(
                f"/projects/{project_id}/bindings", timeout=self._connect_timeout
            )
        except httpx.HTTPError as error:
            raise BrokerUnreachableError(self._base_url) from error

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise BrokerError(response.status_code, "could not read role bindings")

        parsed: Any = response.json()

        if not isinstance(parsed, list):
            raise BrokerError(response.status_code, "bindings returned a non-array body")

        for entry in parsed:
            if isinstance(entry, dict) and entry.get("role") == BINDING_ROLE:
                model_id = entry.get("model_id")

                if isinstance(model_id, str) and model_id:
                    return model_id

        raise BrokerError(response.status_code, f"no {BINDING_ROLE} binding for this project")

    async def invoke(
        self,
        model_id: str,
        prompt: str,
        request_id: str,
        timeout_ms: int,
    ) -> str:
        body: dict[str, Any] = {
            "model_id": model_id,
            "prompt": prompt,
            "role": BINDING_ROLE,
            "mode": "structured",
            "request_id": request_id,
            "timeout_ms": timeout_ms,
        }

        try:
            response = await self._client.post("/invoke", json=body, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise BrokerUnreachableError(self._base_url) from error

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise BrokerError(response.status_code, self._reason(response))

        parsed: Any = response.json()

        if not isinstance(parsed, dict):
            raise BrokerError(response.status_code, "/invoke returned a non-object body")

        answer = parsed.get("response")

        if not isinstance(answer, str) or not answer.strip():
            raise BrokerError(response.status_code, "/invoke returned an empty response")

        return answer

    @staticmethod
    def _reason(response: httpx.Response) -> str:
        try:
            payload: Any = response.json()
        except ValueError:
            return response.text[:200]

        detail = payload.get("detail") if isinstance(payload, dict) else None

        if isinstance(detail, str):
            return detail

        if isinstance(detail, dict):
            reason = detail.get("reason")

            if isinstance(reason, str):
                return reason

        return response.text[:200]
