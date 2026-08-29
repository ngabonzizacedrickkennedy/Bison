from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mediator_service.config import settings
from mediator_service.manifest import (
    CAPABILITY_NAMES,
    ManifestUnavailableError,
    load_manifest,
    manifest_path,
    to_machine_facts,
)


def capability(
    backend: str | None, strength: str, available: list[str] | None = None
) -> dict[str, Any]:
    detected = available if available is not None else ([backend] if backend else [])

    return {"backend": backend, "strength": strength, "available": detected}


def manifest_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": "2026-08-29T09:00:00Z",
        "sandbox": capability("job_object", "medium", ["job_object", "wasm"]),
        "secrets": capability("keytar", "full"),
        "ocr": capability(None, "unavailable"),
        "database": capability("sqlite", "full"),
        "cache": capability("in_process", "medium"),
        "input_injection": capability("pyautogui", "verified"),
        "screen_capture": capability("mss", "full"),
        "hardware": {
            "os_version": "Windows 11 26100",
            "cpu_cores": 8,
            "ram_gb": 16,
            "free_disk_gb": 214.5,
        },
        "budgets": {"local_model_gb": 8, "max_projects": 5},
    }
    document.update(overrides)

    return document


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("BISON_DATA_DIR", str(tmp_path))
    settings.cache_clear()

    yield tmp_path

    settings.cache_clear()


def write_manifest(data_dir: Path, document: dict[str, Any]) -> None:
    (data_dir / "capabilities.json").write_text(json.dumps(document), encoding="utf-8")


def test_the_manifest_is_read_from_the_data_directory(data_dir: Path) -> None:
    write_manifest(data_dir, manifest_document())

    assert manifest_path() == data_dir / "capabilities.json"
    assert load_manifest().schema_version == 1


def test_a_missing_manifest_says_to_run_bootstrap(data_dir: Path) -> None:
    with pytest.raises(ManifestUnavailableError) as caught:
        load_manifest()

    assert "run bootstrap-service first" in str(caught.value)


def test_an_unreadable_manifest_is_reported(data_dir: Path) -> None:
    (data_dir / "capabilities.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(ManifestUnavailableError) as caught:
        load_manifest()

    assert "unreadable" in str(caught.value)


def test_the_hardware_is_carried_into_the_machine_facts(data_dir: Path) -> None:
    write_manifest(data_dir, manifest_document())
    facts = to_machine_facts(load_manifest())

    assert facts.os_version == "Windows 11 26100"
    assert facts.cpu_cores == 8
    assert facts.ram_gb == 16
    assert facts.free_disk_gb == 214.5


def test_every_named_capability_is_carried(data_dir: Path) -> None:
    write_manifest(data_dir, manifest_document())
    facts = to_machine_facts(load_manifest())

    assert [item.name for item in facts.capabilities] == list(CAPABILITY_NAMES)


def test_a_capability_added_to_the_contract_does_not_leak_into_the_prompt(
    data_dir: Path,
) -> None:
    write_manifest(data_dir, manifest_document())
    facts = to_machine_facts(load_manifest())

    assert len(facts.capabilities) == 7
    assert "budgets" not in [item.name for item in facts.capabilities]
    assert "hardware" not in [item.name for item in facts.capabilities]


def test_a_backend_and_its_strength_are_both_kept(data_dir: Path) -> None:
    write_manifest(data_dir, manifest_document())
    facts = to_machine_facts(load_manifest())
    sandbox = next(item for item in facts.capabilities if item.name == "sandbox")

    assert sandbox.backend == "job_object"
    assert sandbox.strength == "medium"


def test_an_unavailable_capability_keeps_its_absent_backend(data_dir: Path) -> None:
    write_manifest(data_dir, manifest_document())
    facts = to_machine_facts(load_manifest())
    ocr = next(item for item in facts.capabilities if item.name == "ocr")

    assert ocr.backend is None
    assert ocr.strength == "unavailable"
