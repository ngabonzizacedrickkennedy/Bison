from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from task_runner_service.jobobject import JobObjectSandbox
from task_runner_service.sandbox import Limits, Mount, OutputChunk, SandboxRequest

CHECK = "import sys, json\nprint(json.dumps({'exe': sys.executable, 'prefix': sys.prefix}))\n"


class Collector:
    def __init__(self) -> None:
        self.chunks: list[str] = []

    async def emit(self, chunk: OutputChunk) -> None:
        self.chunks.append(f"{chunk.stream}: {chunk.text}")

    def text(self) -> str:
        return "".join(self.chunks)[:600].strip()


def direct(interpreter: Path, script: Path) -> dict[str, Any]:
    finished = subprocess.run(
        [str(interpreter), str(script)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    return {
        "exit_code": finished.returncode,
        "stdout": finished.stdout.strip(),
        "stderr": finished.stderr.strip()[:400],
    }


async def sandboxed(interpreter: Path, script: Path, root: Path) -> dict[str, Any]:
    sink = Collector()
    request = SandboxRequest(
        step_id="probe-venv",
        program=str(interpreter),
        arguments=[str(script)],
        working_directory=str(root),
        mounts=[Mount(path=str(root), writable=True)],
        environment={},
        network=False,
        limits=Limits(wall_clock_seconds=120, memory_mb=512, max_output_bytes=65536),
    )

    try:
        result = await JobObjectSandbox().run(request, sink)
    except Exception as error:
        return {"raised": f"{type(error).__name__}: {error}", "output": sink.text()}

    return {
        "exit_code": result.exit_code,
        "terminated_by": result.terminated_by,
        "error_message": result.error_message,
        "output": sink.text(),
        "files_written": len(result.files_written),
    }


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="bison-venv-probe-") as raw:
        root = Path(raw)
        script = root / "check.py"
        script.write_text(CHECK, encoding="utf-8")

        venv.create(root / ".venv", with_pip=True, symlinks=False)
        interpreter = root / ".venv" / "Scripts" / "python.exe"

        report: dict[str, Any] = {
            "interpreter": str(interpreter),
            "exists": interpreter.is_file(),
            "size_bytes": interpreter.stat().st_size if interpreter.is_file() else 0,
            "direct": direct(interpreter, script),
            "sandboxed": await sandboxed(interpreter, script, root),
        }

        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
