from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from bison_contracts import CapabilityManifest, SandboxBackend

from task_runner_service.sandbox import ProgramKind, Sandbox
from task_runner_service.wasm import WasmSandbox

STRENGTH_ORDER: Final[tuple[str, ...]] = ("docker", "job_object", "wasm")


class NoSandboxAvailableError(RuntimeError):
    def __init__(self, kind: ProgramKind, offered: list[str]) -> None:
        listed = ", ".join(offered) or "nothing"
        super().__init__(
            f"no available sandbox can run a {kind} program; this machine offers {listed}"
        )
        self.kind = kind
        self.offered = offered


@dataclass(frozen=True)
class Binding:
    sandbox: Sandbox
    backend: SandboxBackend
    preferred: str | None
    degraded: bool
    reason: str | None


def build(runtime_dir: Path | None = None) -> dict[str, Sandbox]:
    available: dict[str, Sandbox] = {"wasm": WasmSandbox(runtime_dir)}

    if sys.platform == "win32":
        from task_runner_service import integrity
        from task_runner_service.jobobject import JobObjectSandbox

        if integrity.available():
            available["job_object"] = JobObjectSandbox(runtime_dir)

    return available


def rank(backend: str) -> int:
    return STRENGTH_ORDER.index(backend) if backend in STRENGTH_ORDER else len(STRENGTH_ORDER)


def offered(manifest: CapabilityManifest) -> list[str]:
    return [entry.value for entry in manifest.sandbox.available]


def preferred_backend(manifest: CapabilityManifest) -> str | None:
    chosen = manifest.sandbox.backend

    return chosen.value if chosen else None


def explain(preferred: str | None, chosen: str, kind: ProgramKind) -> str | None:
    if preferred is None:
        return f"this machine reported no sandbox backend; running {kind} programs under {chosen}"

    if preferred == chosen:
        return None

    return f"this machine prefers {preferred}, which cannot run {kind} programs; using {chosen}"


def bind(manifest: CapabilityManifest, kind: ProgramKind, sandboxes: dict[str, Sandbox]) -> Binding:
    preferred = preferred_backend(manifest)
    candidates = sorted((name for name in offered(manifest) if name in sandboxes), key=rank)

    for name in candidates:
        sandbox = sandboxes[name]

        if kind not in sandbox.accepts:
            continue

        return Binding(
            sandbox=sandbox,
            backend=SandboxBackend(name),
            preferred=preferred,
            degraded=preferred != name,
            reason=explain(preferred, name, kind),
        )

    raise NoSandboxAvailableError(kind, offered(manifest))
