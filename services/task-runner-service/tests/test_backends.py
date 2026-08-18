from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from bison_contracts import CapabilityManifest, SandboxBackend

from task_runner_service.backends import Binding, NoSandboxAvailableError, bind, build, rank
from task_runner_service.sandbox import (
    Enforcement,
    OutputSink,
    ProgramKind,
    Sandbox,
    SandboxRequest,
    SandboxResult,
    Termination,
)

NEVER = Enforcement(
    filesystem_write_scope=False,
    filesystem_read_scope=False,
    network_isolation=False,
    memory_limit=False,
    process_tree_kill=False,
)


@dataclass
class FakeSandbox:
    name: SandboxBackend
    kinds: frozenset[ProgramKind]

    @property
    def backend(self) -> SandboxBackend:
        return self.name

    @property
    def enforcement(self) -> Enforcement:
        return NEVER

    @property
    def accepts(self) -> frozenset[ProgramKind]:
        return self.kinds

    async def run(self, request: SandboxRequest, sink: OutputSink) -> SandboxResult:
        raise NotImplementedError

    async def terminate(self, step_id: str, reason: Termination) -> bool:
        raise NotImplementedError

    async def terminate_all(self, reason: Termination) -> list[str]:
        raise NotImplementedError


def sandboxes() -> dict[str, Sandbox]:
    return {
        "wasm": FakeSandbox(SandboxBackend.wasm, frozenset({"wasm_module"})),
        "job_object": FakeSandbox(SandboxBackend.job_object, frozenset({"native"})),
    }


def manifest(backend: str | None, available: list[str]) -> CapabilityManifest:
    return CapabilityManifest.model_validate(
        {
            "schema_version": 1,
            "generated_at": "2026-08-18T00:00:00+00:00",
            "sandbox": {"backend": backend, "strength": "medium", "available": available},
            "secrets": {"backend": "age_file", "strength": "medium", "available": ["age_file"]},
            "ocr": {
                "backend": "tesseract_bundled",
                "strength": "full",
                "available": ["tesseract_bundled"],
            },
            "database": {"backend": "sqlite", "strength": "full", "available": ["sqlite"]},
            "cache": {"backend": "in_process", "strength": "full", "available": ["in_process"]},
            "input_injection": {
                "backend": "pyautogui",
                "strength": "verified",
                "available": ["pyautogui"],
            },
            "screen_capture": {"backend": "mss", "strength": "full", "available": ["mss"]},
            "hardware": {
                "ram_gb": 16,
                "free_disk_gb": 84,
                "cpu_cores": 8,
                "os_version": "Windows 11",
            },
            "budgets": {"local_model_gb": 21, "max_projects": 10},
        }
    )


def test_stronger_backends_rank_first() -> None:
    assert rank("docker") < rank("job_object") < rank("wasm")
    assert rank("unknown") > rank("wasm")


def test_the_preferred_backend_is_used_when_it_fits() -> None:
    chosen = bind(manifest("job_object", ["job_object", "wasm"]), "native", sandboxes())

    assert chosen.backend == SandboxBackend.job_object
    assert chosen.preferred == "job_object"
    assert not chosen.degraded
    assert chosen.reason is None


def test_a_backend_this_build_cannot_construct_is_skipped() -> None:
    chosen = bind(manifest("docker", ["docker", "job_object", "wasm"]), "native", sandboxes())

    assert chosen.backend == SandboxBackend.job_object
    assert chosen.preferred == "docker"
    assert chosen.degraded
    assert chosen.reason is not None
    assert "docker" in chosen.reason
    assert "job_object" in chosen.reason


def test_a_preferred_backend_that_cannot_run_the_program_is_skipped() -> None:
    chosen = bind(manifest("job_object", ["job_object", "wasm"]), "wasm_module", sandboxes())

    assert chosen.backend == SandboxBackend.wasm
    assert chosen.degraded
    assert chosen.reason is not None
    assert "wasm_module" in chosen.reason


def test_the_same_machine_binds_differently_per_program_kind() -> None:
    machine = manifest("job_object", ["job_object", "wasm"])
    available = sandboxes()

    native = bind(machine, "native", available)
    module = bind(machine, "wasm_module", available)

    assert native.backend == SandboxBackend.job_object
    assert module.backend == SandboxBackend.wasm


def test_a_machine_reporting_no_backend_is_degraded() -> None:
    chosen = bind(manifest(None, ["wasm"]), "wasm_module", sandboxes())

    assert chosen.backend == SandboxBackend.wasm
    assert chosen.preferred is None
    assert chosen.degraded
    assert chosen.reason is not None
    assert "no sandbox backend" in chosen.reason


def test_availability_order_does_not_override_strength() -> None:
    chosen = bind(manifest(None, ["wasm", "job_object"]), "native", sandboxes())

    assert chosen.backend == SandboxBackend.job_object


def test_a_machine_with_no_usable_backend_is_refused() -> None:
    with pytest.raises(NoSandboxAvailableError, match="native"):
        bind(manifest("wasm", ["wasm"]), "native", sandboxes())


def test_an_empty_availability_list_is_refused() -> None:
    with pytest.raises(NoSandboxAvailableError, match="nothing"):
        bind(manifest(None, []), "native", sandboxes())


def test_a_backend_named_but_not_available_is_not_used() -> None:
    with pytest.raises(NoSandboxAvailableError):
        bind(manifest("job_object", ["wasm"]), "native", sandboxes())


def test_the_binding_carries_the_sandbox_it_chose() -> None:
    chosen = bind(manifest("job_object", ["job_object", "wasm"]), "native", sandboxes())

    assert isinstance(chosen, Binding)
    assert chosen.sandbox.accepts == frozenset({"native"})


def test_build_offers_wasm_everywhere_and_job_objects_on_windows(tmp_path: Path) -> None:
    constructed = build(tmp_path.resolve() / "runs")

    assert "wasm" in constructed

    if sys.platform == "win32":
        assert "job_object" in constructed
    else:
        assert "job_object" not in constructed
