from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mediator_service.broker import (
    BrokerClient,
    BrokerError,
    BrokerUnreachableError,
)

BASE_URL = "http://127.0.0.1:8090"
PROJECT_ID = "prj_1"
REQUEST_ID = "req_1"
TIMEOUT_MS = 120000

BOUND = [
    {"role": "analyst", "model_id": "qwen2.5:7b"},
    {"role": "engine", "model_id": "anthropic/claude-sonnet-4"},
    {"role": "mediator", "model_id": "qwen2.5-coder:7b"},
]


def client(handler: Any) -> BrokerClient:
    return BrokerClient(BASE_URL, 30.0, 5.0, transport=httpx.MockTransport(handler))


def replying(status: int, payload: Any) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


def recording(sent: list[httpx.Request]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)

        if request.url.path.endswith("/bindings"):
            return httpx.Response(200, json=BOUND)

        return httpx.Response(200, json={"response": "an answer"})

    return handler


def body_of(request: httpx.Request) -> dict[str, Any]:
    parsed: Any = json.loads(request.content)

    assert isinstance(parsed, dict)

    return parsed


async def test_bindings_are_read_into_a_map_by_role() -> None:
    broker = client(replying(200, BOUND))

    assert await broker.bindings(PROJECT_ID) == {
        "analyst": "qwen2.5:7b",
        "engine": "anthropic/claude-sonnet-4",
        "mediator": "qwen2.5-coder:7b",
    }

    await broker.close()


async def test_both_bindings_come_from_one_round_trip() -> None:
    sent: list[httpx.Request] = []
    broker = client(recording(sent))

    bound = await broker.bindings(PROJECT_ID)

    assert BrokerClient.binding_for(bound, "engine") == "anthropic/claude-sonnet-4"
    assert BrokerClient.binding_for(bound, "mediator") == "qwen2.5-coder:7b"
    assert len(sent) == 1

    await broker.close()


async def test_a_missing_binding_names_the_role_that_is_missing() -> None:
    with pytest.raises(BrokerError) as caught:
        BrokerClient.binding_for({"mediator": "qwen2.5-coder:7b"}, "engine")

    assert "no engine binding" in caught.value.detail


async def test_an_entry_without_a_model_id_is_skipped() -> None:
    broker = client(replying(200, [{"role": "engine", "model_id": ""}, *BOUND[2:]]))

    assert await broker.bindings(PROJECT_ID) == {"mediator": "qwen2.5-coder:7b"}

    await broker.close()


async def test_a_bindings_body_that_is_not_an_array_is_refused() -> None:
    broker = client(replying(200, {"engine": "x"}))

    with pytest.raises(BrokerError) as caught:
        await broker.bindings(PROJECT_ID)

    assert "non-array" in caught.value.detail

    await broker.close()


async def test_a_bindings_failure_is_reported() -> None:
    broker = client(replying(500, {"detail": "database is locked"}))

    with pytest.raises(BrokerError) as caught:
        await broker.bindings(PROJECT_ID)

    assert caught.value.status == 500

    await broker.close()


async def test_the_engine_is_asked_in_prose_and_the_mediator_in_json() -> None:
    sent: list[httpx.Request] = []
    broker = client(recording(sent))

    await broker.approach(
        "anthropic/claude-sonnet-4", "how would you do this", REQUEST_ID, TIMEOUT_MS
    )
    await broker.tree("qwen2.5-coder:7b", "now build the tree", REQUEST_ID, TIMEOUT_MS)

    first = body_of(sent[0])
    second = body_of(sent[1])

    assert (first["role"], first["mode"]) == ("engine", "completion")
    assert (second["role"], second["mode"]) == ("mediator", "structured")

    await broker.close()


async def test_the_invocation_carries_the_model_and_the_request_id() -> None:
    sent: list[httpx.Request] = []
    broker = client(recording(sent))

    await broker.tree("qwen2.5-coder:7b", "build the tree", REQUEST_ID, TIMEOUT_MS)
    body = body_of(sent[0])

    assert body["model_id"] == "qwen2.5-coder:7b"
    assert body["request_id"] == REQUEST_ID
    assert body["timeout_ms"] == TIMEOUT_MS

    await broker.close()


async def test_the_answer_is_returned_verbatim() -> None:
    broker = client(replying(200, {"response": "  a tree  "}))

    assert await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS) == "  a tree  "

    await broker.close()


async def test_a_role_the_broker_does_not_accept_is_refused_before_the_call() -> None:
    sent: list[httpx.Request] = []
    broker = client(recording(sent))

    with pytest.raises(ValueError):
        await broker.invoke("m", "p", "router", "completion", REQUEST_ID, TIMEOUT_MS)

    assert sent == []

    await broker.close()


async def test_an_empty_response_is_refused() -> None:
    broker = client(replying(200, {"response": "   "}))

    with pytest.raises(BrokerError) as caught:
        await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert "empty response" in caught.value.detail

    await broker.close()


async def test_a_response_without_the_expected_key_is_refused() -> None:
    broker = client(replying(200, {"text": "a tree"}))

    with pytest.raises(BrokerError):
        await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS)

    await broker.close()


async def test_an_invoke_body_that_is_not_an_object_is_refused() -> None:
    broker = client(replying(200, ["a tree"]))

    with pytest.raises(BrokerError) as caught:
        await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert "non-object" in caught.value.detail

    await broker.close()


async def test_a_string_detail_is_surfaced_as_the_reason() -> None:
    broker = client(replying(503, {"detail": "circuit breaker is open"}))

    with pytest.raises(BrokerError) as caught:
        await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert caught.value.detail == "circuit breaker is open"

    await broker.close()


async def test_a_structured_detail_is_unwrapped_to_its_reason() -> None:
    broker = client(replying(503, {"detail": {"reason": "no budget left today"}}))

    with pytest.raises(BrokerError) as caught:
        await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert caught.value.detail == "no budget left today"

    await broker.close()


async def test_a_non_json_body_is_reported_rather_than_crashing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy authentication required</html>")

    broker = client(handler)

    with pytest.raises(BrokerError) as caught:
        await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert "non-JSON" in caught.value.detail

    await broker.close()


async def test_a_non_json_error_body_falls_back_to_its_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    broker = client(handler)

    with pytest.raises(BrokerError) as caught:
        await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert caught.value.detail == "bad gateway"

    await broker.close()


async def test_a_broker_that_is_not_there_is_named() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    broker = client(handler)

    with pytest.raises(BrokerUnreachableError) as caught:
        await broker.tree("m", "p", REQUEST_ID, TIMEOUT_MS)

    assert caught.value.base_url == BASE_URL

    await broker.close()


async def test_an_unreachable_broker_is_named_when_reading_bindings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    broker = client(handler)

    with pytest.raises(BrokerUnreachableError):
        await broker.bindings(PROJECT_ID)

    await broker.close()


async def test_a_trailing_slash_on_the_base_url_does_not_double_up() -> None:
    sent: list[httpx.Request] = []
    broker = BrokerClient(f"{BASE_URL}/", 30.0, 5.0, transport=httpx.MockTransport(recording(sent)))

    await broker.bindings(PROJECT_ID)

    assert sent[0].url.path == f"/projects/{PROJECT_ID}/bindings"

    await broker.close()
