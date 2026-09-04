from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx

from mediator_service.persist import ProjectServiceError, ProjectServiceUnreachableError

ACTOR: Final[str] = "mediator"
OVERALL_ID: Final[str] = "__overall__"
SETTLED_STATES: Final[frozenset[str]] = frozenset({"done", "failed", "skipped", "ignored"})
RUNNABLE_STATES: Final[frozenset[str]] = frozenset({"pending", "ready", "blocked"})


@dataclass(frozen=True)
class Task:
    id: str
    parent_id: str | None
    title: str
    description: str
    kind: str
    state: str
    state_reason: str | None
    depends_on: tuple[str, ...]
    assigned_role: str
    position: int

    @property
    def settled(self) -> bool:
        return self.state in SETTLED_STATES

    @property
    def runnable(self) -> bool:
        return self.state in RUNNABLE_STATES


@dataclass(frozen=True)
class Criterion:
    id: str
    task_id: str
    statement: str
    check_kind: str
    check_spec: dict[str, Any] | None
    weight: int
    status: str

    @property
    def mechanisable(self) -> bool:
        return self.check_kind == "deterministic" and self.check_spec is not None


@dataclass(frozen=True)
class Progress:
    task_id: str
    percentage: float
    criteria_total: int
    criteria_verified: int
    criteria_failed: int
    criteria_ignored: int


@dataclass(frozen=True)
class Snapshot:
    overall: Progress
    per_task: dict[str, Progress]

    def of(self, task_id: str) -> Progress:
        return self.per_task.get(
            task_id,
            Progress(
                task_id=task_id,
                percentage=0.0,
                criteria_total=0,
                criteria_verified=0,
                criteria_failed=0,
                criteria_ignored=0,
            ),
        )


@dataclass(frozen=True)
class Outcome:
    step_id: str
    state: str
    touched_paths: tuple[str, ...]
    exit_code: int | None
    error_message: str | None
    started_at: str | None
    ended_at: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "state": self.state,
            "touched_paths": list(self.touched_paths),
            "exit_code": self.exit_code,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


def text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)

    return value if isinstance(value, str) else ""


def optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)

    return value if isinstance(value, str) and value.strip() else None


def whole(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)

    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def decimal(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)

    if isinstance(value, bool):
        return 0.0

    return float(value) if isinstance(value, int | float) else 0.0


def strings(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)

    if not isinstance(value, list):
        return ()

    return tuple(item for item in value if isinstance(item, str))


def to_task(payload: dict[str, Any]) -> Task:
    return Task(
        id=text(payload, "id"),
        parent_id=optional_text(payload, "parent_id"),
        title=text(payload, "title"),
        description=text(payload, "description"),
        kind=text(payload, "kind"),
        state=text(payload, "state"),
        state_reason=optional_text(payload, "state_reason"),
        depends_on=strings(payload, "depends_on"),
        assigned_role=text(payload, "assigned_role"),
        position=whole(payload, "position"),
    )


def to_criterion(payload: dict[str, Any]) -> Criterion:
    spec = payload.get("check_spec")

    return Criterion(
        id=text(payload, "id"),
        task_id=text(payload, "task_id"),
        statement=text(payload, "statement"),
        check_kind=text(payload, "check_kind"),
        check_spec=spec if isinstance(spec, dict) else None,
        weight=whole(payload, "weight"),
        status=text(payload, "status"),
    )


def to_progress(payload: dict[str, Any]) -> Progress:
    return Progress(
        task_id=text(payload, "task_id"),
        percentage=decimal(payload, "percentage"),
        criteria_total=whole(payload, "criteria_total"),
        criteria_verified=whole(payload, "criteria_verified"),
        criteria_failed=whole(payload, "criteria_failed"),
        criteria_ignored=whole(payload, "criteria_ignored"),
    )


def to_snapshot(payload: dict[str, Any]) -> Snapshot:
    overall = payload.get("overall")
    entries = payload.get("per_task")
    listed = entries if isinstance(entries, list) else []

    per_task = {
        progress.task_id: progress
        for progress in (to_progress(entry) for entry in listed if isinstance(entry, dict))
        if progress.task_id
    }

    return Snapshot(
        overall=to_progress(overall if isinstance(overall, dict) else {"task_id": OVERALL_ID}),
        per_task=per_task,
    )


class ProjectClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._client = httpx.AsyncClient(base_url=self._base_url, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    async def tasks(self, project_id: str) -> tuple[Task, ...]:
        entries = await self._array(f"/projects/{project_id}/tasks")

        return tuple(to_task(entry) for entry in entries)

    async def criteria(self, task_id: str) -> tuple[Criterion, ...]:
        entries = await self._array(f"/tasks/{task_id}/criteria")

        return tuple(to_criterion(entry) for entry in entries)

    async def progress(self, project_id: str) -> Snapshot:
        parsed = await self._object("GET", f"/projects/{project_id}/progress", None)

        return to_snapshot(parsed)

    async def stored_step(self, step_id: str) -> dict[str, Any]:
        return await self._object("GET", f"/steps/{step_id}", None)

    async def stored_plan(self, plan_id: str) -> dict[str, Any]:
        return await self._object("GET", f"/plans/{plan_id}", None)

    async def move_task(self, task_id: str, state: str, reason: str | None) -> Task:
        body: dict[str, Any] = {"state": state, "reason": reason, "actor": ACTOR}
        parsed = await self._object("POST", f"/tasks/{task_id}/state", body)

        return to_task(parsed)

    async def settle_criterion(
        self, criterion_id: str, status: str, reason: str | None
    ) -> Criterion:
        body: dict[str, Any] = {"status": status, "reason": reason, "actor": ACTOR}
        parsed = await self._object("POST", f"/criteria/{criterion_id}/status", body)

        return to_criterion(parsed)

    async def move_step(self, step_id: str, state: str, reason: str | None) -> str:
        body: dict[str, Any] = {"state": state, "reason": reason, "actor": ACTOR}
        parsed = await self._object("POST", f"/steps/{step_id}/transitions", body)

        return text(parsed, "state")

    async def write_record(
        self,
        task_id: str,
        request_id: str,
        halt_reason: str,
        outcomes: tuple[Outcome, ...],
    ) -> str:
        body: dict[str, Any] = {
            "request_id": request_id,
            "halt_reason": halt_reason,
            "step_outcomes": [outcome.payload() for outcome in outcomes],
        }
        parsed = await self._object("POST", f"/tasks/{task_id}/reconciliations", body)

        return text(parsed, "id")

    async def _send(self, method: str, path: str, body: dict[str, Any] | None) -> httpx.Response:
        try:
            return await self._client.request(method, path, json=body, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise ProjectServiceUnreachableError(self._base_url) from error

    async def _object(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        response = await self._send(method, path, body)

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ProjectServiceError(response.status_code, f"{path} was refused")

        parsed: Any = response.json()

        if not isinstance(parsed, dict):
            raise ProjectServiceError(response.status_code, f"{path} returned a non-object body")

        return parsed

    async def _array(self, path: str) -> list[dict[str, Any]]:
        response = await self._send("GET", path, None)

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ProjectServiceError(response.status_code, f"{path} was refused")

        parsed: Any = response.json()

        if not isinstance(parsed, list):
            raise ProjectServiceError(response.status_code, f"{path} returned a non-array body")

        return [item for item in parsed if isinstance(item, dict)]
