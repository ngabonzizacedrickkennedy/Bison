from __future__ import annotations

from typing import Any, Final

import httpx

ENGINE_ROLE: Final[str] = "engine"
MEDIATOR_ROLE: Final[str] = "mediator"

KNOWN_ROLES: Final[frozenset[str]] = frozenset({"analyst", ENGINE_ROLE, MEDIATOR_ROLE, "inspector"})

COMPLETION_MODE: Final[str] = "completion"
STRUCTURED_MODE: Final[str] = "structured"

MAX_REASON_CHARS: Final[int] = 200


class BrokerError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"model-broker responded {status}: {detail}")
        self.status = status
        self.detail = detail


class BrokerUnreachableError(RuntimeError):
    def __init__(self, base_url: str) -> None:
        super().__init__(f"model-broker unreachable at {base_url}")
        self.base_url = base_url


class BrokerClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        connect_timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)
        self._connect_timeout = connect_timeout
        self._client = httpx.AsyncClient(base_url=self._base_url, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    async def bindings(self, project_id: str) -> dict[str, str]:
        try:
            response = await self._client.get(
                f"/projects/{project_id}/bindings", timeout=self._connect_timeout
            )
        except httpx.HTTPError as error:
            raise BrokerUnreachableError(self._base_url) from error

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise BrokerError(response.status_code, "could not read role bindings")

        parsed: Any = self._body(response)

        if not isinstance(parsed, list):
            raise BrokerError(response.status_code, "bindings returned a non-array body")

        collected: dict[str, str] = {}

        for entry in parsed:
            if not isinstance(entry, dict):
                continue

            role = entry.get("role")
            model_id = entry.get("model_id")

            if isinstance(role, str) and isinstance(model_id, str) and model_id:
                collected[role] = model_id

        return collected

    @staticmethod
    def binding_for(bound: dict[str, str], role: str) -> str:
        model_id = bound.get(role)

        if not model_id:
            raise BrokerError(httpx.codes.NOT_FOUND, f"no {role} binding for this project")

        return model_id

    async def invoke(
        self,
        model_id: str,
        prompt: str,
        role: str,
        mode: str,
        request_id: str,
        timeout_ms: int,
    ) -> str:
        if role not in KNOWN_ROLES:
            raise ValueError(f"{role} is not a role the broker accepts")

        body: dict[str, Any] = {
            "model_id": model_id,
            "prompt": prompt,
            "role": role,
            "mode": mode,
            "request_id": request_id,
            "timeout_ms": timeout_ms,
        }

        try:
            response = await self._client.post("/invoke", json=body, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise BrokerUnreachableError(self._base_url) from error

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise BrokerError(response.status_code, self._reason(response))

        parsed: Any = self._body(response)

        if not isinstance(parsed, dict):
            raise BrokerError(response.status_code, "/invoke returned a non-object body")

        answer = parsed.get("response")

        if not isinstance(answer, str) or not answer.strip():
            raise BrokerError(response.status_code, "/invoke returned an empty response")

        return answer

    async def approach(self, model_id: str, prompt: str, request_id: str, timeout_ms: int) -> str:
        return await self.invoke(
            model_id, prompt, ENGINE_ROLE, COMPLETION_MODE, request_id, timeout_ms
        )

    async def tree(self, model_id: str, prompt: str, request_id: str, timeout_ms: int) -> str:
        return await self.invoke(
            model_id, prompt, MEDIATOR_ROLE, STRUCTURED_MODE, request_id, timeout_ms
        )

    @staticmethod
    def _body(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as error:
            raise BrokerError(
                response.status_code, "the broker returned a non-JSON body"
            ) from error

    @staticmethod
    def _reason(response: httpx.Response) -> str:
        try:
            payload: Any = response.json()
        except ValueError:
            return response.text[:MAX_REASON_CHARS]

        detail = payload.get("detail") if isinstance(payload, dict) else None

        if isinstance(detail, str):
            return detail

        if isinstance(detail, dict):
            reason = detail.get("reason")

            if isinstance(reason, str):
                return reason

        return response.text[:MAX_REASON_CHARS]
