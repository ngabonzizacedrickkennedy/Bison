from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx

from mediator_service.checks import payload as check_payload
from mediator_service.sequencing import Ordering
from mediator_service.tree import DraftTask, TreeDraft

TASK_ORIGIN: Final[str] = "mediator"
MAX_REASON_CHARS: Final[int] = 200


class ProjectServiceError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"project-service responded {status}: {detail}")
        self.status = status
        self.detail = detail


class ProjectServiceUnreachableError(RuntimeError):
    def __init__(self, base_url: str) -> None:
        super().__init__(f"project-service unreachable at {base_url}")
        self.base_url = base_url


class PartialTreeError(RuntimeError):
    def __init__(self, created: tuple[str, ...], failed_ref: str, detail: str) -> None:
        super().__init__(
            f"the tree was only partly written: {len(created)} task(s) created before {failed_ref} "
            f"failed with {detail}"
        )
        self.created = created
        self.failed_ref = failed_ref
        self.detail = detail


@dataclass(frozen=True)
class StoredTree:
    task_ids: dict[str, str]
    criterion_ids: dict[str, tuple[str, ...]]

    @property
    def task_count(self) -> int:
        return len(self.task_ids)

    @property
    def criterion_count(self) -> int:
        return sum(len(ids) for ids in self.criterion_ids.values())


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

    async def create_task(self, project_id: str, body: dict[str, Any]) -> str:
        parsed = await self._post(f"/projects/{project_id}/tasks", body)

        return self._identifier(parsed, "task")

    async def create_criterion(self, task_id: str, body: dict[str, Any]) -> str:
        parsed = await self._post(f"/tasks/{task_id}/criteria", body)

        return self._identifier(parsed, "criterion")

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=body, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise ProjectServiceUnreachableError(self._base_url) from error

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ProjectServiceError(response.status_code, self._reason(response))

        try:
            parsed: Any = response.json()
        except ValueError as error:
            raise ProjectServiceError(
                response.status_code, "project-service returned a non-JSON body"
            ) from error

        if not isinstance(parsed, dict):
            raise ProjectServiceError(response.status_code, f"{path} returned a non-object body")

        return parsed

    @staticmethod
    def _identifier(parsed: dict[str, Any], what: str) -> str:
        identifier = parsed.get("id")

        if not isinstance(identifier, str) or not identifier:
            raise ProjectServiceError(httpx.codes.OK, f"the created {what} carried no id")

        return identifier

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


def task_body(task: DraftTask, task_ids: dict[str, str]) -> dict[str, Any]:
    return {
        "title": task.title,
        "description": task.description,
        "origin": TASK_ORIGIN,
        "kind": task.kind,
        "assigned_role": task.assigned_role,
        "parent_id": task_ids[task.parent_ref] if task.parent_ref is not None else None,
        "depends_on": [task_ids[ref] for ref in task.depends_on],
        "position": task.position,
    }


def criterion_body(statement: str, check_kind: str, spec: Any, weight: int) -> dict[str, Any]:
    return {
        "statement": statement,
        "check_kind": check_kind,
        "check_spec": check_payload(spec) if spec is not None else None,
        "weight": weight,
    }


async def store(
    client: ProjectClient,
    draft: TreeDraft,
    ordering: Ordering,
    project_id: str,
) -> StoredTree:
    by_ref = {task.ref: task for task in draft.tasks}
    task_ids: dict[str, str] = {}
    criterion_ids: dict[str, tuple[str, ...]] = {}

    for ref in ordering.creation_order:
        task = by_ref[ref]

        try:
            task_ids[ref] = await client.create_task(project_id, task_body(task, task_ids))
        except (ProjectServiceError, ProjectServiceUnreachableError) as error:
            raise PartialTreeError(tuple(task_ids), ref, str(error)) from error

        collected: list[str] = []

        for criterion in task.criteria:
            body = criterion_body(
                criterion.statement,
                criterion.check_kind,
                criterion.check_spec,
                criterion.weight,
            )

            try:
                collected.append(await client.create_criterion(task_ids[ref], body))
            except (ProjectServiceError, ProjectServiceUnreachableError) as error:
                raise PartialTreeError(tuple(task_ids), ref, str(error)) from error

        criterion_ids[ref] = tuple(collected)

    return StoredTree(task_ids=task_ids, criterion_ids=criterion_ids)
