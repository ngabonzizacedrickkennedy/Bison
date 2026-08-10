from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

CURRENT_VERSION = "v1"

ModelRole = Literal["analyst", "engine", "mediator", "inspector"]


@dataclass(frozen=True, slots=True)
class PromptVersion:
    role: ModelRole
    version: str
    hash: str
    text: str


@cache
def load_prompt(role: ModelRole, version: str = CURRENT_VERSION) -> PromptVersion:
    path = PROMPT_DIR / f"{role}.{version}.md"

    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Prompt not found at {path}. Run `pnpm codegen` to regenerate."
        ) from exc

    if not raw:
        raise ValueError(f"Prompt at {path} is empty.")

    return PromptVersion(
        role=role,
        version=version,
        hash=hashlib.sha256(raw).hexdigest(),
        text=raw.decode("utf8"),
    )


def prompt_ref(role: ModelRole, version: str = CURRENT_VERSION) -> str:
    return f"{role}.{version}.{load_prompt(role, version).hash[:12]}"
