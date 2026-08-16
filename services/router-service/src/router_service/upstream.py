from __future__ import annotations

from typing import Any

import httpx

from router_service.context import BriefFacts, Criterion, HistoryEntry, TaskFacts

SETTLED_STATES = frozenset({"done", "failed", "skipped", "ignored"})


class UpstreamError(RuntimeError):
    def __init__(self, service: str, detail: str) -> None:
        super().__init__(f"{service}: {detail}")
        self.service = service
        self.detail = detail


class ProjectNotFoundError(UpstreamError):
    def __init__(self, project_id: str) -> None:
        super().__init__("project-service", f"project {project_id} not found")


class TaskNotFoundError(UpstreamError):
    def __init__(self, task_id: str) -> None:
        super().__init__("project-service", f"task {task_id} is not in this project")


def text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)

    return value if isinstance(value, str) else ""


def optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)

    return value if isinstance(value, str) and value.strip() else None


def whole(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)

    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def strings(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)

    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


def to_task_facts(payload: dict[str, Any]) -> TaskFacts:
    return TaskFacts(
        title=text(payload, "title"),
        description=text(payload, "description"),
        kind=text(payload, "kind"),
        state=text(payload, "state"),
    )


def to_history(payload: dict[str, Any]) -> HistoryEntry:
    return HistoryEntry(
        title=text(payload, "title"),
        state=text(payload, "state"),
        note=optional_text(payload, "state_reason"),
    )


def to_criterion(payload: dict[str, Any]) -> Criterion:
    return Criterion(
        criterion_id=text(payload, "id"),
        statement=text(payload, "statement"),
        check_kind=text(payload, "check_kind"),
        status=text(payload, "status"),
    )


def to_brief_facts(payload: dict[str, Any]) -> BriefFacts:
    return BriefFacts(
        interpreted_goal=text(payload, "interpreted_goal"),
        project_type=text(payload, "project_type"),
        known_constraints=strings(payload, "known_constraints"),
        out_of_scope=strings(payload, "out_of_scope"),
        assumptions=strings(payload, "assumptions"),
    )


def settled(entries: list[dict[str, Any]], task_id: str) -> list[HistoryEntry]:
    others = [
        entry
        for entry in entries
        if text(entry, "id") != task_id and text(entry, "state") in SETTLED_STATES
    ]
    others.sort(key=lambda entry: whole(entry, "position"), reverse=True)

    return [to_history(entry) for entry in others]


class ProjectClient:
    def __init__(self, base_url: str, timeout_seconds: float, connect_timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)
        self._client = httpx.AsyncClient(base_url=self._base_url)

    async def close(self) -> None:
        await self._client.aclose()

    async def task_and_history(
        self, project_id: str, task_id: str
    ) -> tuple[TaskFacts, list[HistoryEntry]]:
        entries = await self._array(f"/projects/{project_id}/tasks", project_id)
        found = next((entry for entry in entries if text(entry, "id") == task_id), None)

        if found is None:
            raise TaskNotFoundError(task_id)

        return to_task_facts(found), settled(entries, task_id)

    async def criteria(self, task_id: str) -> list[Criterion]:
        response = await self._fetch(f"/tasks/{task_id}/criteria")

        if response.status_code == httpx.codes.NOT_FOUND:
            raise TaskNotFoundError(task_id)

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UpstreamError("project-service", f"criteria responded {response.status_code}")

        parsed: Any = response.json()

        if not isinstance(parsed, list):
            raise UpstreamError("project-service", "criteria returned a non-array body")

        return [to_criterion(entry) for entry in parsed if isinstance(entry, dict)]

    async def brief(self, project_id: str) -> BriefFacts | None:
        path = f"/projects/{project_id}/brief"
        response = await self._fetch(path)

        if response.status_code == httpx.codes.NOT_FOUND:
            return None

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UpstreamError("project-service", f"{path} responded {response.status_code}")

        parsed: Any = response.json()

        if not isinstance(parsed, dict):
            return None

        return to_brief_facts(parsed)

    async def _fetch(self, path: str) -> httpx.Response:
        try:
            return await self._client.get(path, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise UpstreamError("project-service", f"{path} unreachable") from error

    async def _array(self, path: str, project_id: str) -> list[dict[str, Any]]:
        response = await self._fetch(path)

        if response.status_code == httpx.codes.NOT_FOUND:
            raise ProjectNotFoundError(project_id)

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UpstreamError("project-service", f"{path} responded {response.status_code}")

        parsed: Any = response.json()

        if not isinstance(parsed, list):
            raise UpstreamError("project-service", f"{path} returned a non-array body")

        return [item for item in parsed if isinstance(item, dict)]
