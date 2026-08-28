from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mediator_service.broker import BrokerClient
from mediator_service.context import BriefFacts, Capability, MachineFacts, MediatorContext
from mediator_service.decomposition import run
from mediator_service.discipline import TreeRejectedError
from mediator_service.tree import MediatorParseError

BASE_URL = "http://127.0.0.1:8090"
PROJECT_ID = "prj_1"
REQUEST_ID = "req_1"

BOUND = [
    {"role": "engine", "model_id": "anthropic/claude-sonnet-4"},
    {"role": "mediator", "model_id": "qwen2.5-coder:7b"},
]

APPROACH = "Create the schema first, then the API, then verify the endpoint answers."


def context() -> MediatorContext:
    return MediatorContext(
        brief=BriefFacts(
            interpreted_goal="Stand up a task tracker with a REST API",
            project_type="software",
            summary="A small tracker backed by SQLite",
            known_constraints=["No admin rights"],
            seeded_success_criteria=["The API answers on port 8000"],
        ),
        machine=MachineFacts(
            os_version="Windows 11 26100",
            cpu_cores=8,
            ram_gb=16,
            free_disk_gb=214.5,
            capabilities=[Capability(name="sandbox", backend="job_object", strength="medium")],
        ),
        scope_root=r"C:\projects\tracker",
    )


def criterion(statement: str) -> dict[str, Any]:
    return {
        "statement": statement,
        "check_kind": "deterministic",
        "check_spec": {"type": "file_exists", "path": "schema.sql"},
        "weight": 1,
    }


def task(ref: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ref": ref,
        "parent_ref": None,
        "title": f"Task {ref}",
        "description": "",
        "kind": "code",
        "assigned_role": "engine",
        "depends_on": [],
        "criteria": [criterion(f"The file {ref}.sql is present")],
    }
    base.update(overrides)

    return base


def tree_json(*tasks: dict[str, Any]) -> str:
    entries = list(tasks) if tasks else [task("schema")]

    return json.dumps({"approach_summary": "Build it in three parts", "tasks": entries})


class Broker:
    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.sent: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bindings"):
            return httpx.Response(200, json=BOUND)

        parsed: Any = json.loads(request.content)
        self.sent.append(parsed)

        return httpx.Response(200, json={"response": self.answers.pop(0)})

    def client(self) -> BrokerClient:
        return BrokerClient(BASE_URL, 30.0, 5.0, transport=httpx.MockTransport(self.handler))

    @property
    def prompts(self) -> list[str]:
        return [str(entry["prompt"]) for entry in self.sent]

    @property
    def roles(self) -> list[str]:
        return [str(entry["role"]) for entry in self.sent]


async def decompose(broker: Broker, repair_attempts: int = 2) -> Any:
    client = broker.client()

    try:
        return await run(
            client,
            context(),
            project_id=PROJECT_ID,
            request_id=REQUEST_ID,
            engine_prompt_name="engine",
            engine_prompt_version="v1",
            mediator_prompt_name="mediator",
            mediator_prompt_version="v1",
            budget_chars=24000,
            timeout_ms=120000,
            repair_attempts=repair_attempts,
        )
    finally:
        await client.close()


async def test_a_clean_run_returns_a_draft_and_an_ordering() -> None:
    broker = Broker(APPROACH, tree_json(task("schema"), task("api", depends_on=["schema"])))
    result = await decompose(broker)

    assert [item.ref for item in result.draft.tasks] == ["schema", "api"]
    assert result.ordering.order == ("schema", "api")
    assert result.attempts == 1
    assert result.repaired is False


async def test_the_engine_is_asked_first_and_its_approach_reaches_the_mediator() -> None:
    broker = Broker(APPROACH, tree_json())
    result = await decompose(broker)

    assert broker.roles == ["engine", "mediator"]
    assert "Do not return JSON" in broker.prompts[0]
    assert APPROACH in broker.prompts[1]
    assert result.approach == APPROACH


async def test_the_brief_reaches_both_roles() -> None:
    broker = Broker(APPROACH, tree_json())

    await decompose(broker)

    for prompt in broker.prompts:
        assert "Stand up a task tracker" in prompt
        assert "sandbox: job_object" in prompt


async def test_both_bindings_are_resolved_and_recorded() -> None:
    broker = Broker(APPROACH, tree_json())
    result = await decompose(broker)

    assert result.engine_model_id == "anthropic/claude-sonnet-4"
    assert result.mediator_model_id == "qwen2.5-coder:7b"


async def test_the_prompt_hashes_are_recorded_for_both_roles() -> None:
    broker = Broker(APPROACH, tree_json())
    result = await decompose(broker)

    assert result.engine_prompt.name == "engine"
    assert result.mediator_prompt.name == "mediator"
    assert len(result.engine_prompt.hash) == 64
    assert result.engine_prompt.hash != result.mediator_prompt.hash


async def test_an_unparseable_tree_is_repaired() -> None:
    broker = Broker(APPROACH, "I would start with the schema.", tree_json())
    result = await decompose(broker)

    assert result.attempts == 2
    assert result.repaired is True
    assert "could not be used" in broker.prompts[2]


async def test_the_repair_says_what_was_wrong() -> None:
    broker = Broker(APPROACH, "no json here", tree_json())

    await decompose(broker)

    assert "no JSON object" in broker.prompts[2]


async def test_an_undisciplined_tree_is_repaired() -> None:
    broker = Broker(
        APPROACH,
        tree_json(task("db", criteria=[criterion("The database is set up")])),
        tree_json(),
    )
    result = await decompose(broker)

    assert result.attempts == 2
    assert "summary rather than a criterion" in broker.prompts[2]


async def test_every_finding_is_handed_back_in_one_repair() -> None:
    broken = tree_json(
        task("a", criteria=[criterion("The database is set up")]),
        task("b", criteria=[]),
        task("c", criteria=[criterion("The build command returns 0")]),
    )
    broker = Broker(APPROACH, broken, tree_json())
    result = await decompose(broker)

    assert result.attempts == 2
    assert "(1)" in broker.prompts[2]
    assert "(3)" in broker.prompts[2]


async def test_the_approach_is_never_repaired() -> None:
    broker = Broker(APPROACH, "not json", tree_json())

    await decompose(broker)

    assert broker.roles == ["engine", "mediator", "mediator"]


async def test_a_cycle_survives_parsing_and_discipline_and_is_caught_by_sequencing() -> None:
    cyclic = tree_json(
        task("a", depends_on=["b"]),
        task("b", depends_on=["a"]),
    )
    broker = Broker(APPROACH, cyclic, tree_json())
    result = await decompose(broker)

    assert result.attempts == 2


async def test_a_tree_that_never_becomes_usable_raises_the_last_failure() -> None:
    broker = Broker(APPROACH, "not json", "still not json", "nope")

    with pytest.raises(MediatorParseError):
        await decompose(broker, repair_attempts=2)


async def test_a_tree_that_stays_undisciplined_raises_its_findings() -> None:
    broken = tree_json(task("a", criteria=[criterion("The database is set up")]))
    broker = Broker(APPROACH, broken, broken, broken)

    with pytest.raises(TreeRejectedError) as caught:
        await decompose(broker, repair_attempts=2)

    assert caught.value.findings


async def test_no_repair_attempts_means_one_try() -> None:
    broker = Broker(APPROACH, "not json")

    with pytest.raises(MediatorParseError):
        await decompose(broker, repair_attempts=0)

    assert broker.roles == ["engine", "mediator"]


async def test_the_ordering_lowers_a_parent_dependency_to_its_leaves() -> None:
    nested = tree_json(
        task("setup", criteria=[]),
        task("setup.db", parent_ref="setup"),
        task("setup.env", parent_ref="setup"),
        task("build", depends_on=["setup"]),
    )
    broker = Broker(APPROACH, nested)
    result = await decompose(broker)

    assert result.attempts == 1
    assert result.ordering.order == ("setup.db", "setup.env", "build")
    assert result.ordering.dependencies("build") == ("setup.db", "setup.env")
