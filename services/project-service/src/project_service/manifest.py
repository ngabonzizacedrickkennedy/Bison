from __future__ import annotations

import json
from pathlib import Path

from bison_contracts import CapabilityManifest
from project_service.database import data_dir


class ManifestUnavailableError(RuntimeError):
    pass


def manifest_path() -> Path:
    return data_dir() / "capabilities.json"


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
