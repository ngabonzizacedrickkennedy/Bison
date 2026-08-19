from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from collections.abc import Mapping
from pathlib import Path

VENV_DIRECTORY = "envs"

BIN_DIRECTORY = "Scripts" if os.name == "nt" else "bin"

INTERPRETER_NAME = "python.exe" if os.name == "nt" else "python"

PYTHON_STEMS = frozenset({"python", "python3", "pythonw"})

MARKER = "pyvenv.cfg"

CREATE_TIMEOUT_SECONDS = 120

SLUG_LENGTH = 40

DIGEST_LENGTH = 12

_locks: dict[Path, asyncio.Lock] = {}


class EnvironmentUnavailableError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def slug(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "-" for character in key
    )[:SLUG_LENGTH].strip("-")

    return f"{cleaned}-{digest}" if cleaned else digest


def home(root: Path, key: str) -> Path:
    return root / VENV_DIRECTORY / slug(key)


def interpreter(venv: Path) -> Path:
    return venv / BIN_DIRECTORY / INTERPRETER_NAME


def complete(venv: Path) -> bool:
    return (venv / MARKER).is_file() and interpreter(venv).is_file()


def executable() -> str:
    found = shutil.which("uv")

    if found is None:
        raise EnvironmentUnavailableError(
            "uv is not on PATH; per-task environments cannot be built"
        )

    return found


def lock(venv: Path) -> asyncio.Lock:
    if venv not in _locks:
        _locks[venv] = asyncio.Lock()

    return _locks[venv]


async def create(venv: Path) -> None:
    venv.parent.mkdir(parents=True, exist_ok=True)

    process = await asyncio.create_subprocess_exec(
        executable(),
        "venv",
        str(venv),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        _out, err = await asyncio.wait_for(process.communicate(), CREATE_TIMEOUT_SECONDS)
    except TimeoutError as expired:
        process.kill()

        raise EnvironmentUnavailableError(
            f"uv venv did not finish within {CREATE_TIMEOUT_SECONDS} seconds"
        ) from expired

    if process.returncode != 0:
        detail = err.decode("utf-8", "replace").strip() or f"uv venv exited {process.returncode}"

        raise EnvironmentUnavailableError(detail)


async def ensure(root: Path, key: str) -> Path:
    venv = home(root, key)

    async with lock(venv):
        if complete(venv):
            return venv

        await create(venv)

        if not complete(venv):
            raise EnvironmentUnavailableError(f"the environment at {venv} is incomplete")

    return venv


def resolve(program: str, venv: Path) -> str:
    if Path(program).stem.lower() in PYTHON_STEMS:
        return str(interpreter(venv))

    return program


def overlay(environment: Mapping[str, str], venv: Path) -> dict[str, str]:
    binaries = str(venv / BIN_DIRECTORY)
    inherited = environment.get("PATH", "")

    merged = dict(environment)
    merged["VIRTUAL_ENV"] = str(venv)
    merged["PATH"] = f"{binaries}{os.pathsep}{inherited}" if inherited else binaries
    merged["PYTHONNOUSERSITE"] = "1"
    merged.pop("PYTHONHOME", None)

    return merged
