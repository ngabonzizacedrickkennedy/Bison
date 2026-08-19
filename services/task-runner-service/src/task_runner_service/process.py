from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pywintypes
import win32api
import win32con
import win32event
import win32file
import win32pipe
import win32process
import win32security

CREATE_SUSPENDED = 0x00000004

CREATE_NO_WINDOW = 0x08000000

CREATE_UNICODE_ENVIRONMENT = 0x00000400

STARTF_USESTDHANDLES = 0x00000100

ERROR_BROKEN_PIPE = 109

INFINITE = 0xFFFFFFFF

PIPE_BUFFER_BYTES = 64 * 1024

READ_CHUNK_BYTES = 64 * 1024

DESKTOP = "winsta0\\default"


@dataclass
class Launch:
    process: int
    thread: int
    pid: int
    stdout: int
    stderr: int


def inheritable() -> Any:
    attributes = win32security.SECURITY_ATTRIBUTES()
    attributes.bInheritHandle = True

    return attributes


def pipe() -> tuple[int, int]:
    read, write = win32pipe.CreatePipe(inheritable(), PIPE_BUFFER_BYTES)

    win32api.SetHandleInformation(read, win32con.HANDLE_FLAG_INHERIT, 0)

    return read, write


def null_input() -> int:
    handle: int = win32file.CreateFile(
        "NUL",
        win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
        inheritable(),
        win32con.OPEN_EXISTING,
        0,
        None,
    )

    return handle


def start(
    program: str,
    arguments: Sequence[str],
    working_directory: Path,
    environment: Mapping[str, str],
    token: int,
) -> Launch:
    out_read, out_write = pipe()
    err_read, err_write = pipe()
    stdin = null_input()

    startup = win32process.STARTUPINFO()
    startup.dwFlags = STARTF_USESTDHANDLES
    startup.lpDesktop = DESKTOP
    startup.hStdInput = stdin
    startup.hStdOutput = out_write
    startup.hStdError = err_write

    command = subprocess.list2cmdline([program, *arguments])
    flags = CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT

    try:
        process, thread, pid, _thread_id = win32process.CreateProcessAsUser(
            token,
            program,
            command,
            None,
            None,
            True,
            flags,
            dict(environment),
            str(working_directory),
            startup,
        )
    except BaseException:
        win32api.CloseHandle(out_read)
        win32api.CloseHandle(err_read)

        raise
    finally:
        win32api.CloseHandle(out_write)
        win32api.CloseHandle(err_write)
        win32api.CloseHandle(stdin)

    return Launch(process=process, thread=thread, pid=pid, stdout=out_read, stderr=err_read)


def resume(launch: Launch) -> None:
    win32process.ResumeThread(launch.thread)


def read_blocking(handle: int) -> bytes:
    try:
        _code, data = win32file.ReadFile(handle, READ_CHUNK_BYTES)
    except pywintypes.error as error:
        if error.winerror == ERROR_BROKEN_PIPE:
            return b""

        raise

    chunk: bytes = data

    return chunk


async def read(handle: int) -> bytes:
    return await asyncio.to_thread(read_blocking, handle)


async def wait(launch: Launch) -> int:
    await asyncio.to_thread(win32event.WaitForSingleObject, launch.process, INFINITE)

    code: int = win32process.GetExitCodeProcess(launch.process)

    return code


def close(launch: Launch) -> None:
    for handle in (launch.stdout, launch.stderr, launch.thread, launch.process):
        with suppress(BaseException):
            win32api.CloseHandle(handle)
