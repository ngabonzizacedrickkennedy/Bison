from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

CURRENT_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class PromptVersion:
    name: str
    version: str
    hash: str
    text: str


@cache
def load_prompt(name: str, version: str = CURRENT_VERSION) -> PromptVersion:
    path = PROMPT_DIR / f"{name}.{version}.md"

    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Prompt not found at {path}. Run `pnpm codegen` to regenerate."
        ) from exc

    if not raw:
        raise ValueError(f"Prompt at {path} is empty.")

    return PromptVersion(
        name=name,
        version=version,
        hash=hashlib.sha256(raw).hexdigest(),
        text=raw.decode("utf8"),
    )


def prompt_ref(name: str, version: str = CURRENT_VERSION) -> str:
    return f"{name}.{version}.{load_prompt(name, version).hash[:12]}"
