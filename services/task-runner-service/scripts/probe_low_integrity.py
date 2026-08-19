from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import win32api
import win32event
import win32process
import win32security

LOW_INTEGRITY_SID = "S-1-16-4096"

DISABLE_MAX_PRIVILEGE = 0x1

SE_GROUP_INTEGRITY = 0x00000020

SYSTEM_MANDATORY_LABEL_NO_WRITE_UP = 0x1

LABEL_SECURITY_INFORMATION = 0x00000010

SE_FILE_OBJECT = 1

ACL_REVISION = 2

OBJECT_INHERIT_ACE = 0x1

CONTAINER_INHERIT_ACE = 0x2

CREATE_NO_WINDOW = 0x08000000

TOKEN_ACCESS = (
    win32security.TOKEN_DUPLICATE
    | win32security.TOKEN_QUERY
    | win32security.TOKEN_ASSIGN_PRIMARY
    | win32security.TOKEN_ADJUST_DEFAULT
)

WAIT_MILLISECONDS = 15000


def windows() -> bool:
    return os.name == "nt"


def stage(message: str) -> None:
    print(f"-- {message}")


def low_sid() -> object:
    return win32security.ConvertStringSidToSid(LOW_INTEGRITY_SID)


def restricted_token() -> int:
    source = win32security.OpenProcessToken(win32api.GetCurrentProcess(), TOKEN_ACCESS)
    token: int = win32security.CreateRestrictedToken(source, DISABLE_MAX_PRIVILEGE, [], [], [])

    return token


def lower_integrity(token: int) -> None:
    win32security.SetTokenInformation(
        token, win32security.TokenIntegrityLevel, (low_sid(), SE_GROUP_INTEGRITY)
    )


def label_low(directory: Path) -> None:
    sacl = win32security.ACL()
    sacl.AddMandatoryAce(
        ACL_REVISION,
        OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
        SYSTEM_MANDATORY_LABEL_NO_WRITE_UP,
        low_sid(),
    )

    win32security.SetNamedSecurityInfo(
        str(directory),
        SE_FILE_OBJECT,
        LABEL_SECURITY_INFORMATION,
        None,
        None,
        None,
        sacl,
    )


def launch(token: int, program: str, command: str, working_directory: Path) -> int:
    startup = win32process.STARTUPINFO()
    startup.lpDesktop = "winsta0\\default"

    handle, thread, _pid, _tid = win32process.CreateProcessAsUser(
        token,
        program,
        command,
        None,
        None,
        False,
        CREATE_NO_WINDOW,
        None,
        str(working_directory),
        startup,
    )

    win32event.WaitForSingleObject(handle, WAIT_MILLISECONDS)
    code: int = win32process.GetExitCodeProcess(handle)

    win32api.CloseHandle(thread)
    win32api.CloseHandle(handle)

    return code


def main() -> int:
    if not windows():
        print("this probe only runs on windows")

        return 1

    scope = Path(tempfile.mkdtemp(prefix="bison-low-")).resolve()
    inside = scope / "inside.txt"
    outside = (Path.home() / "bison-low-integrity-probe.txt").resolve()

    outside.unlink(missing_ok=True)

    comspec = Path(win32api.GetSystemDirectory()) / "cmd.exe"
    command = f'"{comspec}" /c echo inside>"{inside}" & echo outside>"{outside}"'

    try:
        stage("creating a restricted token from this process")
        token = restricted_token()

        stage("lowering the token to low integrity")
        lower_integrity(token)

        stage(f"labelling {scope} low integrity")
        label_low(scope)

        stage("launching cmd.exe under the low token")
        code = launch(token, str(comspec), command, scope)

        print()
        print(f"exit code             {code}")
        print(f"wrote inside scope    {inside.is_file()}")
        print(f"wrote outside scope   {outside.is_file()}")

        contained = inside.is_file() and not outside.is_file()

        print()
        print("RESULT " + ("contained" if contained else "NOT contained"))

        return 0 if contained else 2
    finally:
        outside.unlink(missing_ok=True)
        shutil.rmtree(scope, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
