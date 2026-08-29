from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from bison_contracts import CapabilityManifest

from mediator_service.config import settings
from mediator_service.context import Capability, MachineFacts

CAPABILITY_NAMES: Final[tuple[str, ...]] = (
    "sandbox",
    "secrets",
    "ocr",
    "database",
    "cache",
    "input_injection",
    "screen_capture",
)


class ManifestUnavailableError(RuntimeError):
    pass


def manifest_path() -> Path:
    return settings().data_dir / "capabilities.json"


def load_manifest() -> CapabilityManifest:
    path = manifest_path()

    if not path.is_file():
        raise ManifestUnavailableError(
            f"capability manifest not found at {path}; run bootstrap-service first"
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestUnavailableError(f"capability manifest at {path} is unreadable") from error

    return CapabilityManifest.model_validate(raw)


def to_machine_facts(manifest: CapabilityManifest) -> MachineFacts:
    capabilities: list[Capability] = []

    for name in CAPABILITY_NAMES:
        entry = getattr(manifest, name)
        capabilities.append(Capability(name=name, backend=entry.backend, strength=entry.strength))

    hardware = manifest.hardware

    return MachineFacts(
        os_version=hardware.os_version,
        cpu_cores=hardware.cpu_cores,
        ram_gb=hardware.ram_gb,
        free_disk_gb=hardware.free_disk_gb,
        capabilities=capabilities,
    )
