from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Final

import httpx

from mediator_service import resolve
from mediator_service.upstream import optional_text, strings, text, whole

TASK_RUNNER_SERVICE: Final[str] = "task-runner"

SUCCEEDED: Final[str] = "succeeded"
FAILED: Final[str] = "failed"
ABORTED: Final[str] = "aborted"

OUTPUT_EVENT: Final[str] = "output"
RESULT_EVENT: Final[str] = "result"
WRITE_EVENT: Final[str] = "write"
ERROR_EVENT: Final[str] = "error"

MAX_REASON_CHARS: Final[int] = 200


class RouterError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"router-service responded {status}: {detail}")
        self.status = status
        self.detail = detail


class RouterUnreachableError(RuntimeError):
    def __init__(self, base_url: str) -> None:
        super().__init__(f"router-service unreachable at {base_url}")
        self.base_url = base_url


class RunnerError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"task-runner responded {status}: {detail}")
        self.status = status
        self.detail = detail


class RunnerUnreachableError(RuntimeError):
    def __init__(self, base_url: str) -> None:
        super().__init__(f"task-runner unreachable at {base_url}")
        self.base_url = base_url


class RunnerStreamError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class UnroutableStepError(RuntimeError):
    def __init__(self, step_id: str, service: str) -> None:
        super().__init__(
            f"step {step_id} is routed to {service!r}, which the mediator cannot dispatch"
        )
        self.step_id = step_id
        self.service = service


def flag(payload: dict[str, Any], key: str) -> bool:
    return payload.get(key) is True


def optional_whole(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)

    if isinstance(value, bool) or not isinstance(value, int):
        return None

    return value


def numbers(payload: dict[str, Any], key: str) -> tuple[int, ...]:
    value = payload.get(key)

    if not isinstance(value, list):
        return ()

    return tuple(item for item in value if isinstance(item, int) and not isinstance(item, bool))


def written_paths(payload: dict[str, Any]) -> tuple[str, ...]:
    value = payload.get("files_written")
    entries = value if isinstance(value, list) else []

    return tuple(
        entry["path"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("path"), str) and entry["path"]
    )


def reason(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text[:MAX_REASON_CHARS]

    if isinstance(payload, dict):
        detail = payload.get("detail")

        if isinstance(detail, str):
            return detail

    return response.text[:MAX_REASON_CHARS]


def content_of(action: dict[str, Any]) -> str:
    value = action.get("content")

    if not isinstance(value, str):
        raise resolve.UnrunnableActionError("a write_file action needs a content string")

    return value


@dataclass(frozen=True)
class Step:
    step_id: str
    position: int
    description: str
    service: str
    action: dict[str, Any] | None
    requires_confirmation: bool
    confirmation_reason: str | None
    on_failure: str
    reversible: bool
    criterion_refs: tuple[str, ...]
    effects: dict[str, Any]
    raw: dict[str, Any]

    @property
    def writes_file(self) -> bool:
        return isinstance(self.action, dict) and self.action.get("type") == resolve.WRITE_FILE

    @property
    def runnable(self) -> bool:
        return resolve.runnable(self.action)

    @property
    def dispatchable(self) -> bool:
        return self.service == TASK_RUNNER_SERVICE and (self.writes_file or self.runnable)

    @property
    def needs_network(self) -> bool:
        return flag(self.effects, "network") or flag(self.effects, "installs_packages")


@dataclass(frozen=True)
class Plan:
    plan_id: str
    project_id: str
    task_id: str
    request_id: str
    scope_root: str
    intent: str
    rationale: str
    steps: tuple[Step, ...]
    gated_count: int
    model_id: str
    prompt_name: str
    prompt_version: str
    prompt_hash: str

    @property
    def steps_total(self) -> int:
        return len(self.steps)


@dataclass(frozen=True)
class Output:
    step_id: str
    stream: str
    sequence: int
    text: str


@dataclass(frozen=True)
class Result:
    step_id: str
    state: str
    exit_code: int | None
    terminated_by: str | None
    error_message: str | None
    touched_paths: tuple[str, ...]
    ports_opened: tuple[int, ...]
    started_at: str | None
    ended_at: str | None

    @property
    def ok(self) -> bool:
        return self.state == SUCCEEDED


Event = Output | Result


def to_step(payload: dict[str, Any]) -> Step:
    action = payload.get("action")
    effects = payload.get("effects")

    return Step(
        step_id=text(payload, "step_id"),
        position=whole(payload, "position"),
        description=text(payload, "description"),
        service=text(payload, "service"),
        action=action if isinstance(action, dict) else None,
        requires_confirmation=flag(payload, "requires_confirmation"),
        confirmation_reason=optional_text(payload, "confirmation_reason"),
        on_failure=text(payload, "on_failure"),
        reversible=flag(payload, "reversible"),
        criterion_refs=strings(payload, "criterion_refs"),
        effects=effects if isinstance(effects, dict) else {},
        raw=payload,
    )


def to_plan(payload: dict[str, Any]) -> Plan:
    entries = payload.get("steps")
    listed = entries if isinstance(entries, list) else []

    return Plan(
        plan_id=text(payload, "plan_id"),
        project_id=text(payload, "project_id"),
        task_id=text(payload, "task_id"),
        request_id=text(payload, "request_id"),
        scope_root=text(payload, "scope_root"),
        intent=text(payload, "intent"),
        rationale=text(payload, "rationale"),
        steps=tuple(to_step(entry) for entry in listed if isinstance(entry, dict)),
        gated_count=whole(payload, "gated_count"),
        model_id=text(payload, "model_id"),
        prompt_name=text(payload, "prompt_name"),
        prompt_version=text(payload, "prompt_version"),
        prompt_hash=text(payload, "prompt_hash"),
    )


def state_of(exit_code: int | None, terminated_by: str | None, error_message: str | None) -> str:
    if terminated_by is not None:
        return ABORTED

    if error_message is not None:
        return FAILED

    return SUCCEEDED if exit_code == 0 else FAILED


def to_output(payload: dict[str, Any]) -> Output:
    return Output(
        step_id=text(payload, "step_id"),
        stream=text(payload, "stream"),
        sequence=whole(payload, "sequence"),
        text=text(payload, "text"),
    )


def to_result(payload: dict[str, Any]) -> Result:
    exit_code = optional_whole(payload, "exit_code")
    terminated_by = optional_text(payload, "terminated_by")
    error_message = optional_text(payload, "error_message")

    return Result(
        step_id=text(payload, "step_id"),
        state=state_of(exit_code, terminated_by, error_message),
        exit_code=exit_code,
        terminated_by=terminated_by,
        error_message=error_message,
        touched_paths=written_paths(payload) + strings(payload, "files_deleted"),
        ports_opened=numbers(payload, "ports_opened"),
        started_at=optional_text(payload, "started_at"),
        ended_at=optional_text(payload, "ended_at"),
    )


def to_write_result(payload: dict[str, Any]) -> Result:
    error_message = optional_text(payload, "error_message")

    return Result(
        step_id=text(payload, "step_id"),
        state=FAILED if error_message is not None else SUCCEEDED,
        exit_code=None,
        terminated_by=None,
        error_message=error_message,
        touched_paths=written_paths(payload),
        ports_opened=(),
        started_at=optional_text(payload, "started_at"),
        ended_at=optional_text(payload, "ended_at"),
    )


def to_failure(payload: dict[str, Any]) -> Result:
    detail = text(payload, "detail")

    return Result(
        step_id=text(payload, "step_id"),
        state=FAILED,
        exit_code=None,
        terminated_by=None,
        error_message=detail if detail else "the runner reported an error with no detail",
        touched_paths=(),
        ports_opened=(),
        started_at=None,
        ended_at=None,
    )


def decode(line: str, path: str) -> Event | None:
    if not line.strip():
        return None

    try:
        parsed: Any = json.loads(line)
    except ValueError as error:
        raise RunnerStreamError(f"{path} emitted a line that is not JSON") from error

    if not isinstance(parsed, dict):
        raise RunnerStreamError(f"{path} emitted a line that is not an object")

    name = parsed.get("event")

    if name == OUTPUT_EVENT:
        return to_output(parsed)

    if name == RESULT_EVENT:
        return to_result(parsed)

    if name == WRITE_EVENT:
        return to_write_result(parsed)

    if name == ERROR_EVENT:
        return to_failure(parsed)

    raise RunnerStreamError(f"{path} emitted an unknown event {name!r}")


class RouterClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        connect_timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)
        self._client = httpx.AsyncClient(base_url=self._base_url, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    async def plan(self, project_id: str, task_id: str, request_id: str) -> Plan:
        path = f"/projects/{project_id}/tasks/{task_id}/plan"

        try:
            response = await self._client.post(
                path, params={"request_id": request_id}, timeout=self._timeout
            )
        except httpx.HTTPError as error:
            raise RouterUnreachableError(self._base_url) from error

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise RouterError(response.status_code, reason(response))

        try:
            parsed: Any = response.json()
        except ValueError as error:
            raise RouterError(response.status_code, f"{path} returned a non-JSON body") from error

        if not isinstance(parsed, dict):
            raise RouterError(response.status_code, f"{path} returned a non-object body")

        return to_plan(parsed)


class RunnerClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        connect_timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)
        self._client = httpx.AsyncClient(base_url=self._base_url, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    def run_body(
        self, step: Step, scope_root: str, task_id: str, confirmed: bool
    ) -> dict[str, Any]:
        call = resolve.invocation(step.action)

        return {
            "scope_root": scope_root,
            "task_id": task_id,
            "step": step.raw,
            "confirmed": confirmed,
            "program": call.program,
            "arguments": list(call.arguments),
            "network": step.needs_network,
        }

    def write_body(
        self, step: Step, scope_root: str, task_id: str, confirmed: bool
    ) -> dict[str, Any]:
        action = step.action if step.action is not None else {}

        return {
            "scope_root": scope_root,
            "task_id": task_id,
            "step": step.raw,
            "confirmed": confirmed,
            "path": resolve.text(action, "path", resolve.WRITE_FILE),
            "content": content_of(action),
        }

    async def dispatch(
        self, step: Step, scope_root: str, task_id: str, confirmed: bool
    ) -> AsyncIterator[Event]:
        if step.service != TASK_RUNNER_SERVICE:
            raise UnroutableStepError(step.step_id, step.service)

        if step.writes_file:
            path = f"/steps/{step.step_id}/write"
            payload = self.write_body(step, scope_root, task_id, confirmed)
        else:
            path = f"/steps/{step.step_id}/run"
            payload = self.run_body(step, scope_root, task_id, confirmed)

        async for event in self._stream(path, payload):
            yield event

    async def _stream(self, path: str, payload: dict[str, Any]) -> AsyncIterator[Event]:
        try:
            async with self._client.stream(
                "POST", path, json=payload, timeout=self._timeout
            ) as response:
                if response.status_code >= httpx.codes.BAD_REQUEST:
                    await response.aread()

                    raise RunnerError(response.status_code, reason(response))

                async for line in response.aiter_lines():
                    event = decode(line, path)

                    if event is not None:
                        yield event
        except httpx.HTTPError as error:
            raise RunnerUnreachableError(self._base_url) from error
