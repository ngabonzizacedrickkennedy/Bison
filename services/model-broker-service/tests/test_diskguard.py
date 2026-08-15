from __future__ import annotations

from model_broker_service import diskguard


def test_allows_a_pull_that_fits() -> None:
    verdict = diskguard.evaluate(40.0, [4.36], 4.9)

    assert verdict.allowed
    assert verdict.reason is None
    assert verdict.used_gb == 4.36


def test_refuses_a_pull_that_exceeds_the_budget() -> None:
    verdict = diskguard.evaluate(40.0, [4.36], 40.0)

    assert not verdict.allowed
    assert verdict.reason is not None
    assert "44.36" in verdict.reason


def test_refuses_when_the_size_is_unknown() -> None:
    verdict = diskguard.evaluate(40.0, [], None)

    assert not verdict.allowed
    assert verdict.incoming_gb == 0.0


def test_allows_a_pull_that_lands_exactly_on_the_budget() -> None:
    verdict = diskguard.evaluate(40.0, [10.0], 30.0)

    assert verdict.allowed


def test_counts_every_installed_model() -> None:
    verdict = diskguard.evaluate(40.0, [4.36, 9.0, 20.0], 9.0)

    assert not verdict.allowed
    assert verdict.used_gb == 33.36
