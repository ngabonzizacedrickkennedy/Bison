from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mediator_service.dispatch import (
    ABORTED,
    FAILED,
    SUCCEEDED,
    Output,
    Result,
    RouterClient,
    RouterError,
    RouterUnreachableError,
    RunnerClient,
    RunnerError,
    RunnerStreamError,
    RunnerUnreachableError,
    UnroutableStepError,
    state_of,
    to_failure,
    to_plan,
    to_result,
    to_step,
    to_write_result,
)
from mediator_service.resolve import UnrunnableActionError

ROUTER_URL = "http://router.test"
RUNNER_URL = "http://runner.test"

PROJECT_ID = "p-1"
TASK_ID = "t-1"
STEP_ID = "s-1"
REQUEST_ID = "r-1"
SCOPE_ROOT = "C:\\scope"

DIGEST = "a" * 64


def effects_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "writes_paths": ["C:\\scope\\schema.sql"],
        "deletes_paths": [],
        "network": False,
        "installs_packages": False,
        "needs_credentials": False,
        "drives_input": False,
        "reversible": True,
    }
    base.update(overrides)

    return base


def write_action() -> dict[str, Any]:
    return {"type": "write_file", "path": "C:\\scope\\schema.sql", "content": "create table t;"}


def script_action() -> dict[str, Any]:
    return {"type": "run_python_script", "script_path": "build.py", "arguments": ["--fast"]}


def install_action() -> dict[str, Any]:
    return {"type": "install_python_packages", "packages": ["httpx"]}


def step_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "step_id": STEP_ID,
        "position": 0,
        "description": "write the schema file",
        "service": "task-runner",
        "action": write_action(),
        "requires_confirmation": False,
        "confirmation_reason": None,
        "on_failure": "abort",
        "reversible": True,
        "criterion_refs": ["c-1"],
        "effects": effects_body(),
    }
    base.update(overrides)

    return base


def plan_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "plan_id": "pl-1",
        "project_id": PROJECT_ID,
        "task_id": TASK_ID,
        "request_id": REQUEST_ID,
        "scope_root": SCOPE_ROOT,
        "intent": "create the schema",
        "rationale": "the task asks for a table",
        "steps": [step_body()],
        "steps_total": 1,
        "gated_count": 0,
        "model_id": "qwen2.5-coder:7b",
        "prompt_name": "router",
        "prompt_version": "v4",
        "prompt_hash": "d9223d1149c4",
        "attempts": 1,
        "repaired": False,
    }
    base.update(overrides)

    return base


def result_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event": "result",
        "step_id": STEP_ID,
        "backend": "job_object",
        "exit_code": 0,
        "terminated_by": None,
        "error_message": None,
        "files_written": [{"path": "C:\\scope\\out.txt", "sha256": DIGEST, "size_bytes": 12}],
        "files_deleted": ["C:\\scope\\stale.txt"],
        "files_written_total": 1,
        "files_deleted_total": 1,
        "files_truncated": False,
        "ports_opened": [8000],
        "output_bytes": 5,
        "output_truncated": False,
        "started_at": "2026-01-01T00:00:00+00:00",
        "ended_at": "2026-01-01T00:00:01+00:00",
    }
    base.update(overrides)

    return base


def write_result_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event": "write",
        "step_id": STEP_ID,
        "path": "C:\\scope\\schema.sql",
        "files_written": [{"path": "C:\\scope\\schema.sql", "sha256": DIGEST, "size_bytes": 15}],
        "error_message": None,
        "started_at": "2026-01-01T00:00:00+00:00",
        "ended_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)

    return base


def output_body(sequence: int, message: str) -> dict[str, Any]:
    return {
        "event": "output",
        "step_id": STEP_ID,
        "stream": "stdout",
        "sequence": sequence,
        "text": message,
    }


def ndjson(*events: dict[str, Any]) -> bytes:
    return b"".join((json.dumps(event) + "\n").encode("utf-8") for event in events)


class Recorder:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)

        return self._responses.pop(0) if self._responses else httpx.Response(200, json={})

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def sent(self) -> dict[str, Any]:
        parsed: Any = json.loads(self.last.content.decode("utf-8"))

        assert isinstance(parsed, dict)

        return parsed


class Refuser:
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)


def router_for(recorder: Recorder) -> RouterClient:
    return RouterClient(ROUTER_URL, 5.0, 1.0, transport=recorder.transport())


def runner_for(recorder: Recorder) -> RunnerClient:
    return RunnerClient(RUNNER_URL, 5.0, 1.0, transport=recorder.transport())


def stream_response(payload: bytes) -> httpx.Response:
    return httpx.Response(200, content=payload, headers={"content-type": "application/x-ndjson"})


async def collect(client: RunnerClient, step: Any, confirmed: bool = True) -> list[Output | Result]:
    events: list[Output | Result] = []

    async for event in client.dispatch(step, SCOPE_ROOT, TASK_ID, confirmed):
        events.append(event)

    return events


def test_a_plan_is_read_into_its_steps() -> None:
    plan = to_plan(plan_body())

    assert plan.plan_id == "pl-1"
    assert plan.scope_root == SCOPE_ROOT
    assert plan.prompt_version == "v4"
    assert plan.steps_total == 1
    assert plan.steps[0].step_id == STEP_ID


def test_the_step_the_router_sent_is_carried_through_untouched() -> None:
    body = step_body()
    step = to_step(body)

    assert step.raw == body
    assert step.raw["effects"] == body["effects"]


def test_a_plan_missing_everything_reads_empty_rather_than_raising() -> None:
    plan = to_plan({})

    assert plan.plan_id == ""
    assert plan.steps == ()
    assert plan.steps_total == 0


def test_a_step_missing_everything_reads_empty_rather_than_raising() -> None:
    step = to_step({})

    assert step.step_id == ""
    assert step.action is None
    assert step.effects == {}
    assert not step.dispatchable


def test_a_write_step_is_recognised_as_a_write_not_a_run() -> None:
    step = to_step(step_body())

    assert step.writes_file
    assert not step.runnable
    assert step.dispatchable


def test_a_script_step_is_recognised_as_runnable() -> None:
    step = to_step(step_body(action=script_action()))

    assert step.runnable
    assert not step.writes_file
    assert step.dispatchable


def test_a_step_for_another_service_is_not_dispatchable() -> None:
    step = to_step(step_body(service="automation"))

    assert not step.dispatchable


def test_a_step_with_no_action_is_not_dispatchable() -> None:
    step = to_step(step_body(action=None))

    assert not step.dispatchable


def test_an_install_needs_the_network_even_when_effects_do_not_say_so() -> None:
    step = to_step(step_body(action=install_action(), effects=effects_body(installs_packages=True)))

    assert step.needs_network


def test_a_plain_script_does_not_ask_for_the_network() -> None:
    step = to_step(step_body(action=script_action()))

    assert not step.needs_network


def test_a_declared_network_effect_is_honoured() -> None:
    step = to_step(step_body(action=script_action(), effects=effects_body(network=True)))

    assert step.needs_network


def test_a_clean_exit_is_a_success() -> None:
    assert state_of(0, None, None) == SUCCEEDED


def test_a_non_zero_exit_is_a_failure() -> None:
    assert state_of(1, None, None) == FAILED


def test_a_termination_is_an_abort_whatever_the_exit_code_says() -> None:
    assert state_of(0, "halt", None) == ABORTED


def test_an_error_message_is_a_failure() -> None:
    assert state_of(None, None, "the sandbox refused") == FAILED


def test_a_result_carries_every_path_the_step_touched() -> None:
    result = to_result(result_body())

    assert result.touched_paths == ("C:\\scope\\out.txt", "C:\\scope\\stale.txt")
    assert result.ports_opened == (8000,)
    assert result.ok


def test_a_terminated_result_reads_as_aborted() -> None:
    result = to_result(result_body(exit_code=None, terminated_by="halt"))

    assert result.state == ABORTED
    assert not result.ok


def test_a_write_result_succeeds_when_no_error_is_reported() -> None:
    result = to_write_result(write_result_body())

    assert result.ok
    assert result.exit_code is None
    assert result.touched_paths == ("C:\\scope\\schema.sql",)


def test_a_write_result_fails_when_an_error_is_reported() -> None:
    result = to_write_result(write_result_body(error_message="the path is outside scope"))

    assert result.state == FAILED
    assert result.error_message == "the path is outside scope"


def test_an_error_event_becomes_a_failed_result_carrying_the_detail() -> None:
    result = to_failure({"event": "error", "step_id": STEP_ID, "detail": "the venv is missing"})

    assert result.state == FAILED
    assert result.error_message == "the venv is missing"


def test_an_error_event_with_no_detail_still_says_something() -> None:
    result = to_failure({"event": "error", "step_id": STEP_ID})

    assert result.error_message == "the runner reported an error with no detail"


async def test_the_plan_request_carries_the_correlation_id() -> None:
    recorder = Recorder([httpx.Response(200, json=plan_body())])
    client = router_for(recorder)

    plan = await client.plan(PROJECT_ID, TASK_ID, REQUEST_ID)

    assert recorder.last.method == "POST"
    assert recorder.last.url.path == f"/projects/{PROJECT_ID}/tasks/{TASK_ID}/plan"
    assert recorder.last.url.params["request_id"] == REQUEST_ID
    assert plan.request_id == REQUEST_ID

    await client.close()


async def test_a_refused_plan_raises_with_the_reason_the_router_gave() -> None:
    recorder = Recorder([httpx.Response(502, json={"detail": "the plan was rejected"})])
    client = router_for(recorder)

    with pytest.raises(RouterError) as raised:
        await client.plan(PROJECT_ID, TASK_ID, REQUEST_ID)

    assert raised.value.status == 502
    assert raised.value.detail == "the plan was rejected"

    await client.close()


async def test_a_non_object_plan_body_is_refused() -> None:
    recorder = Recorder([httpx.Response(200, json=[])])
    client = router_for(recorder)

    with pytest.raises(RouterError):
        await client.plan(PROJECT_ID, TASK_ID, REQUEST_ID)

    await client.close()


async def test_a_router_that_cannot_be_reached_is_named_as_such() -> None:
    client = RouterClient(ROUTER_URL, 5.0, 1.0, transport=Refuser().transport())

    with pytest.raises(RouterUnreachableError):
        await client.plan(PROJECT_ID, TASK_ID, REQUEST_ID)

    await client.close()


async def test_a_script_step_is_posted_to_run_as_bare_python() -> None:
    recorder = Recorder([stream_response(ndjson(result_body()))])
    client = runner_for(recorder)
    step = to_step(step_body(action=script_action()))

    await collect(client, step)

    assert recorder.last.url.path == f"/steps/{STEP_ID}/run"

    body = recorder.sent()

    assert body["program"] == "python"
    assert body["arguments"] == ["build.py", "--fast"]
    assert body["scope_root"] == SCOPE_ROOT
    assert body["task_id"] == TASK_ID
    assert body["confirmed"] is True

    await client.close()


async def test_an_install_step_is_posted_with_the_network_open() -> None:
    recorder = Recorder([stream_response(ndjson(result_body()))])
    client = runner_for(recorder)
    step = to_step(step_body(action=install_action(), effects=effects_body(installs_packages=True)))

    await collect(client, step)

    body = recorder.sent()

    assert body["arguments"] == ["-m", "pip", "install", "httpx"]
    assert body["network"] is True

    await client.close()


async def test_a_write_step_is_posted_to_write_with_its_path_and_content() -> None:
    recorder = Recorder([stream_response(ndjson(write_result_body()))])
    client = runner_for(recorder)
    step = to_step(step_body())

    await collect(client, step)

    assert recorder.last.url.path == f"/steps/{STEP_ID}/write"

    body = recorder.sent()

    assert body["path"] == "C:\\scope\\schema.sql"
    assert body["content"] == "create table t;"

    await client.close()


async def test_the_step_block_reaches_the_runner_exactly_as_the_router_wrote_it() -> None:
    recorder = Recorder([stream_response(ndjson(write_result_body()))])
    client = runner_for(recorder)
    original = step_body()

    await collect(client, to_step(original))

    assert recorder.sent()["step"] == original

    await client.close()


async def test_output_arrives_before_the_result_and_in_order() -> None:
    recorder = Recorder(
        [
            stream_response(
                ndjson(output_body(0, "starting\n"), output_body(1, "done\n"), result_body())
            )
        ]
    )
    client = runner_for(recorder)

    events = await collect(client, to_step(step_body(action=script_action())))

    assert len(events) == 3

    first, second, last = events

    assert isinstance(first, Output)
    assert isinstance(second, Output)
    assert isinstance(last, Result)
    assert (first.sequence, second.sequence) == (0, 1)
    assert last.ok

    await client.close()


async def test_a_write_stream_yields_one_result() -> None:
    recorder = Recorder([stream_response(ndjson(write_result_body()))])
    client = runner_for(recorder)

    events = await collect(client, to_step(step_body()))

    assert len(events) == 1
    assert isinstance(events[0], Result)

    await client.close()


async def test_a_refusal_from_the_runner_raises_with_its_reason() -> None:
    recorder = Recorder([httpx.Response(403, json={"detail": "writes outside the project"})])
    client = runner_for(recorder)

    with pytest.raises(RunnerError) as raised:
        await collect(client, to_step(step_body()))

    assert raised.value.status == 403
    assert raised.value.detail == "writes outside the project"

    await client.close()


async def test_a_line_that_is_not_json_stops_the_stream() -> None:
    recorder = Recorder([stream_response(b"not json\n")])
    client = runner_for(recorder)

    with pytest.raises(RunnerStreamError):
        await collect(client, to_step(step_body()))

    await client.close()


async def test_an_unknown_event_stops_the_stream_rather_than_being_ignored() -> None:
    recorder = Recorder([stream_response(ndjson({"event": "invented", "step_id": STEP_ID}))])
    client = runner_for(recorder)

    with pytest.raises(RunnerStreamError):
        await collect(client, to_step(step_body()))

    await client.close()


async def test_blank_lines_are_skipped() -> None:
    recorder = Recorder([stream_response(b"\n" + ndjson(write_result_body()) + b"\n")])
    client = runner_for(recorder)

    events = await collect(client, to_step(step_body()))

    assert len(events) == 1

    await client.close()


async def test_a_step_for_another_service_is_never_sent() -> None:
    recorder = Recorder([])
    client = runner_for(recorder)

    with pytest.raises(UnroutableStepError):
        await collect(client, to_step(step_body(service="automation")))

    assert recorder.requests == []

    await client.close()


async def test_a_step_with_no_action_is_never_sent() -> None:
    recorder = Recorder([])
    client = runner_for(recorder)

    with pytest.raises(UnrunnableActionError):
        await collect(client, to_step(step_body(action=None)))

    assert recorder.requests == []

    await client.close()


async def test_a_runner_that_cannot_be_reached_is_named_as_such() -> None:
    client = RunnerClient(RUNNER_URL, 5.0, 1.0, transport=Refuser().transport())

    with pytest.raises(RunnerUnreachableError):
        await collect(client, to_step(step_body()))

    await client.close()
