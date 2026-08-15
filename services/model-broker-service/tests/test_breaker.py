from __future__ import annotations

import asyncio

import pytest

from model_broker_service.backends.breaker import (
    BackendCircuitOpenError,
    CircuitBreaker,
    CircuitState,
)


async def succeed() -> str:
    return "ok"


async def fail() -> str:
    raise RuntimeError("backend down")


async def test_stays_closed_while_calls_succeed() -> None:
    breaker = CircuitBreaker(fail_max=3, reset_seconds=60.0)

    for _ in range(5):
        assert await breaker.run("test", succeed) == "ok"

    assert breaker.state() is CircuitState.CLOSED


async def test_opens_after_the_failure_threshold() -> None:
    breaker = CircuitBreaker(fail_max=3, reset_seconds=60.0)

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await breaker.run("test", fail)

    assert breaker.state() is CircuitState.OPEN


async def test_refuses_without_calling_the_backend_when_open() -> None:
    breaker = CircuitBreaker(fail_max=1, reset_seconds=60.0)
    calls = 0

    async def counted() -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("backend down")

    with pytest.raises(RuntimeError):
        await breaker.run("test", counted)

    with pytest.raises(BackendCircuitOpenError):
        await breaker.run("test", counted)

    assert calls == 1


async def test_a_success_resets_the_failure_count() -> None:
    breaker = CircuitBreaker(fail_max=3, reset_seconds=60.0)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.run("test", fail)

    await breaker.run("test", succeed)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.run("test", fail)

    assert breaker.state() is CircuitState.CLOSED


async def test_half_opens_after_the_cooldown() -> None:
    breaker = CircuitBreaker(fail_max=1, reset_seconds=0.2)

    with pytest.raises(RuntimeError):
        await breaker.run("test", fail)

    assert breaker.state() is CircuitState.OPEN

    await asyncio.sleep(0.25)

    assert breaker.state() is CircuitState.HALF_OPEN


async def test_a_successful_trial_closes_the_circuit() -> None:
    breaker = CircuitBreaker(fail_max=1, reset_seconds=0.2)

    with pytest.raises(RuntimeError):
        await breaker.run("test", fail)

    await asyncio.sleep(0.25)

    assert await breaker.run("test", succeed) == "ok"
    assert breaker.state() is CircuitState.CLOSED


async def test_a_failed_trial_reopens_immediately() -> None:
    breaker = CircuitBreaker(fail_max=5, reset_seconds=0.2)

    for _ in range(5):
        with pytest.raises(RuntimeError):
            await breaker.run("test", fail)

    assert breaker.state() is CircuitState.OPEN

    await asyncio.sleep(0.25)

    assert breaker.state() is CircuitState.HALF_OPEN

    with pytest.raises(RuntimeError):
        await breaker.run("test", fail)

    assert breaker.state() is CircuitState.OPEN


async def test_only_one_trial_call_is_admitted_when_half_open() -> None:
    breaker = CircuitBreaker(fail_max=1, reset_seconds=0.2)
    started = asyncio.Event()
    release = asyncio.Event()
    admitted = 0

    async def slow() -> str:
        nonlocal admitted
        admitted += 1
        started.set()
        await release.wait()
        return "ok"

    with pytest.raises(RuntimeError):
        await breaker.run("test", fail)

    await asyncio.sleep(0.25)

    trial = asyncio.create_task(breaker.run("test", slow))
    await started.wait()

    with pytest.raises(BackendCircuitOpenError):
        await breaker.run("test", slow)

    release.set()
    await trial

    assert admitted == 1
