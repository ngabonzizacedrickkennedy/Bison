from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

import psutil

from task_runner_service import integrity, process

LISTEN_PORT = 47913

SETTLE_SECONDS = 3.0

ENVIRONMENT_KEYS = ("SYSTEMROOT", "PATH", "TEMP")

SOURCE = f"""
import socket, time
server = socket.socket()
server.bind(("127.0.0.1", {LISTEN_PORT}))
server.listen(1)
time.sleep(10)
"""


def stage(message: str) -> None:
    print(f"-- {message}")


def per_process(pid: int) -> list[object]:
    try:
        found: list[object] = list(psutil.Process(pid).net_connections(kind="inet"))

        return found
    except psutil.AccessDenied:
        print("per-process: ACCESS DENIED")

        return []
    except psutil.NoSuchProcess:
        print("per-process: NO SUCH PROCESS")

        return []


def system_wide(pid: int) -> list[object]:
    try:
        table = list(psutil.net_connections(kind="inet"))
    except psutil.AccessDenied:
        print("system-wide: ACCESS DENIED")

        return []

    owned = [entry for entry in table if entry.pid == pid]
    matching = [entry for entry in table if entry.laddr and entry.laddr.port == LISTEN_PORT]

    print(f"system-wide total     {len(table)}")
    print(f"on our port           {matching}")

    return owned


def descendants(pid: int) -> set[int]:
    found = {pid}

    with suppress(psutil.NoSuchProcess):
        found.update(child.pid for child in psutil.Process(pid).children(recursive=True))

    return found


def listening(pid: int) -> list[int]:
    tree = descendants(pid)

    print(f"process tree          {sorted(tree)}")

    try:
        table = list(psutil.net_connections(kind="inet"))
    except psutil.AccessDenied:
        print("system-wide: ACCESS DENIED")

        return []

    return sorted(
        {
            entry.laddr.port
            for entry in table
            if entry.pid in tree and entry.status == psutil.CONN_LISTEN and entry.laddr
        }
    )


def main() -> int:
    if os.name != "nt":
        print("this probe only runs on windows")

        return 1

    scope = Path(tempfile.mkdtemp(prefix="bison-ports-")).resolve()
    script = scope / "listen.py"
    script.write_text(SOURCE, newline="\n")

    environment = {key: os.environ[key] for key in ENVIRONMENT_KEYS if key in os.environ}

    stage("creating a low integrity token")
    token = integrity.restricted_token()

    stage(f"labelling {scope} low integrity")
    integrity.label_low(scope)

    stage("launching a listener under the low token")
    launch = process.start(sys.executable, [str(script)], scope, environment, token)

    try:
        process.resume(launch)

        time.sleep(SETTLE_SECONDS)

        import win32process

        code = win32process.GetExitCodeProcess(launch.process)
        alive = code == 259

        ports = listening(launch.pid)
        print(f"expected owner        2616 was seen earlier; ours is {launch.pid}")

        print()
        print(f"child pid             {launch.pid}")
        print(f"still running         {alive}")
        print(f"exit code            {'-' if alive else code}")
        print(f"ports observed        {ports}")

        if not alive:
            print()
            print("stderr:")
            print(process.read_blocking(launch.stderr).decode("utf-8", "replace"))

        print()
        print("RESULT " + ("observable" if LISTEN_PORT in ports else "NOT observable"))

        return 0 if LISTEN_PORT in ports else 2
    finally:
        process.close(launch)
        integrity.close(token)
        integrity.apply_label(scope, None)
        shutil.rmtree(scope, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
