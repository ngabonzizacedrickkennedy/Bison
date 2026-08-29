from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mediator_service.checks import FileExists
from mediator_service.persist import (
    PartialTreeError,
    ProjectClient,
    ProjectServiceError,
    ProjectServiceUnreachableError,
    store,
)
from mediator_service.sequencing import Node, build
from mediator_service.tree import DraftCriterion, DraftTask, TreeDraft

BASE_URL = "http://127.0.0.1:8070"
PROJECT_ID = "prj_1"


def criterion(statement: str, weight: int = 1, inspected: bool = False) -> DraftCriterion:
    return DraftCriterion(
        statement=statement,
        check_kind="inspected" if inspected else "deterministic",
        check_spec=None if inspected else FileExists(path="out.txt"),
        weight=weight,
    )


def task(
    ref: str,
    *,
    parent: str | None = None,
    depends_on: tuple[str, ...] = (),
    position: int = 0,
    criteria: tuple[DraftCriterion, ...] = (),
) -> DraftTask:
    return DraftTask(
        ref=ref,
        parent_ref=parent,
        title=f"Task {ref}",
        description="does something",
        kind="code",
        assigned_role="engine",
        depends_on=depends_on,
        criteria=criteria,
        position=position,
    )


def draft_of(*tasks: DraftTask) -> TreeDraft:
    return TreeDraft(approach_summary="Build it", tasks=tasks)


def ordering_of(draft: TreeDraft) -> Any:
    return build(
        [
            Node(
                id=item.ref,
                parent_id=item.parent_ref,
                depends_on=item.depends_on,
                position=item.position,
            )
            for item in draft.tasks
        ]
    )


class Service:
    def __init__(self, fail_on: int | None = None, status: int = 500) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.fail_on = fail_on
        self.status = status
        self._tasks = 0
        self._criteria = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed: Any = json.loads(request.content)
        path = request.url.path
        self.sent.append((path, parsed))

        if self.fail_on is not None and len(self.sent) == self.fail_on:
            return httpx.Response(self.status, json={"detail": "state is locked"})

        if path.endswith("/tasks"):
            self._tasks += 1

            return httpx.Response(201, json={"id": f"tsk_{self._tasks}"})

        self._criteria += 1

        return httpx.Response(201, json={"id": f"crt_{self._criteria}"})

    def client(self) -> ProjectClient:
        return ProjectClient(BASE_URL, 30.0, transport=httpx.MockTransport(self.handler))

    def bodies(self, suffix: str) -> list[dict[str, Any]]:
        return [body for path, body in self.sent if path.endswith(suffix)]


async def write(service: Service, draft: TreeDraft) -> Any:
    client = service.client()

    try:
        return await store(client, draft, ordering_of(draft), PROJECT_ID)
    finally:
        await client.close()


async def test_every_task_and_criterion_is_created() -> None:
    draft = draft_of(
        task("a", criteria=(criterion("The file a.txt is present"),), position=0),
        task("b", criteria=(criterion("The file b.txt is present"),), position=1),
    )
    service = Service()
    stored = await write(service, draft)

    assert stored.task_count == 2
    assert stored.criterion_count == 2
    assert stored.task_ids == {"a": "tsk_1", "b": "tsk_2"}


async def test_a_parent_id_is_a_real_id_by_the_time_its_child_is_created() -> None:
    draft = draft_of(
        task("setup", position=0),
        task("setup.db", parent="setup", criteria=(criterion("Table users exists"),), position=0),
    )
    service = Service()
    stored = await write(service, draft)
    child = service.bodies("/tasks")[1]

    assert child["parent_id"] == stored.task_ids["setup"]


async def test_a_root_task_has_no_parent_id() -> None:
    service = Service()

    await write(service, draft_of(task("a", criteria=(criterion("The file a.txt is present"),))))

    assert service.bodies("/tasks")[0]["parent_id"] is None


async def test_a_forward_declared_dependency_is_already_a_real_id() -> None:
    draft = draft_of(
        task("consumer", depends_on=("producer",), position=0),
        task("producer", position=1),
    )
    service = Service()
    stored = await write(service, draft)
    bodies = service.bodies("/tasks")

    assert bodies[0]["title"] == "Task producer"
    assert bodies[1]["depends_on"] == [stored.task_ids["producer"]]


async def test_a_dependency_on_a_parent_is_recorded_as_that_parent_s_id() -> None:
    draft = draft_of(
        task("setup", position=0),
        task("setup.db", parent="setup", position=0),
        task("build", depends_on=("setup",), position=1),
    )
    service = Service()
    stored = await write(service, draft)
    build_body = next(body for body in service.bodies("/tasks") if body["title"] == "Task build")

    assert build_body["depends_on"] == [stored.task_ids["setup"]]


async def test_the_origin_is_set_here_and_not_taken_from_the_model() -> None:
    service = Service()

    await write(service, draft_of(task("a", criteria=(criterion("The file a.txt is present"),))))

    assert service.bodies("/tasks")[0]["origin"] == "mediator"


async def test_the_task_fields_are_passed_through() -> None:
    service = Service()

    await write(service, draft_of(task("a", position=3)))
    body = service.bodies("/tasks")[0]

    assert body["kind"] == "code"
    assert body["assigned_role"] == "engine"
    assert body["position"] == 3
    assert body["description"] == "does something"


async def test_a_deterministic_criterion_carries_its_check_spec() -> None:
    service = Service()

    await write(service, draft_of(task("a", criteria=(criterion("The file a.txt is present"),))))
    body = service.bodies("/criteria")[0]

    assert body["check_kind"] == "deterministic"
    assert body["check_spec"] == {"type": "file_exists", "path": "out.txt"}


async def test_an_inspected_criterion_sends_a_null_check_spec() -> None:
    draft = draft_of(task("a", criteria=(criterion("It matches the design", inspected=True),)))
    service = Service()

    await write(service, draft)
    body = service.bodies("/criteria")[0]

    assert body["check_kind"] == "inspected"
    assert body["check_spec"] is None


async def test_the_criterion_weight_is_carried() -> None:
    draft = draft_of(task("a", criteria=(criterion("The file a.txt is present", weight=7),)))
    service = Service()

    await write(service, draft)

    assert service.bodies("/criteria")[0]["weight"] == 7


async def test_criteria_are_created_against_their_own_task() -> None:
    draft = draft_of(
        task("a", criteria=(criterion("The file a.txt is present"),), position=0),
        task("b", criteria=(criterion("The file b.txt is present"),), position=1),
    )
    service = Service()
    stored = await write(service, draft)
    paths = [path for path, _ in service.sent if path.endswith("/criteria")]

    assert paths[0] == f"/tasks/{stored.task_ids['a']}/criteria"
    assert paths[1] == f"/tasks/{stored.task_ids['b']}/criteria"


async def test_criterion_ids_are_returned_grouped_by_ref() -> None:
    draft = draft_of(
        task(
            "a",
            criteria=(
                criterion("The file a.txt is present"),
                criterion("The file b.txt is present"),
            ),
        )
    )
    service = Service()
    stored = await write(service, draft)

    assert stored.criterion_ids == {"a": ("crt_1", "crt_2")}


async def test_a_task_without_criteria_creates_none() -> None:
    service = Service()
    stored = await write(service, draft_of(task("a")))

    assert stored.criterion_ids == {"a": ()}
    assert service.bodies("/criteria") == []


async def test_a_failure_part_way_through_reports_what_was_already_created() -> None:
    draft = draft_of(
        task("a", criteria=(criterion("The file a.txt is present"),), position=0),
        task("b", position=1),
        task("c", position=2),
    )
    service = Service(fail_on=3)

    with pytest.raises(PartialTreeError) as caught:
        await write(service, draft)

    assert caught.value.created == ("a",)
    assert caught.value.failed_ref == "b"
    assert "state is locked" in caught.value.detail


async def test_a_failure_creating_a_criterion_names_its_task() -> None:
    draft = draft_of(task("a", criteria=(criterion("The file a.txt is present"),)))
    service = Service(fail_on=2)

    with pytest.raises(PartialTreeError) as caught:
        await write(service, draft)

    assert caught.value.failed_ref == "a"
    assert caught.value.created == ("a",)


async def test_a_service_that_is_not_there_is_reported_as_a_partial_write() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = ProjectClient(BASE_URL, 30.0, transport=httpx.MockTransport(handler))

    with pytest.raises(PartialTreeError) as caught:
        await store(client, draft_of(task("a")), ordering_of(draft_of(task("a"))), PROJECT_ID)

    assert "unreachable" in caught.value.detail

    await client.close()


async def test_a_created_task_without_an_id_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"title": "Task a"})

    client = ProjectClient(BASE_URL, 30.0, transport=httpx.MockTransport(handler))

    with pytest.raises(ProjectServiceError):
        await client.create_task(PROJECT_ID, {"title": "Task a"})

    await client.close()


async def test_a_non_json_body_is_reported_rather_than_crashing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, text="<html>proxy authentication required</html>")

    client = ProjectClient(BASE_URL, 30.0, transport=httpx.MockTransport(handler))

    with pytest.raises(ProjectServiceError) as caught:
        await client.create_task(PROJECT_ID, {"title": "Task a"})

    assert "non-JSON" in caught.value.detail

    await client.close()


async def test_a_structured_detail_is_unwrapped_to_its_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": {"reason": "project is archived"}})

    client = ProjectClient(BASE_URL, 30.0, transport=httpx.MockTransport(handler))

    with pytest.raises(ProjectServiceError) as caught:
        await client.create_task(PROJECT_ID, {"title": "Task a"})

    assert caught.value.detail == "project is archived"

    await client.close()


async def test_an_unreachable_service_is_named() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    client = ProjectClient(BASE_URL, 30.0, transport=httpx.MockTransport(handler))

    with pytest.raises(ProjectServiceUnreachableError) as caught:
        await client.create_task(PROJECT_ID, {"title": "Task a"})

    assert caught.value.base_url == BASE_URL

    await client.close()
