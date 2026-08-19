from __future__ import annotations

from pathlib import Path
from typing import Any

import pywintypes
import win32api
import win32security

LOW_INTEGRITY_SID = "S-1-16-4096"

DISABLE_MAX_PRIVILEGE = 0x1

SE_GROUP_INTEGRITY = 0x00000020

SE_FILE_OBJECT = 1

LABEL_SECURITY_INFORMATION = 0x00000010

SYSTEM_MANDATORY_LABEL_ACE_TYPE = 0x11

SYSTEM_MANDATORY_LABEL_NO_WRITE_UP = 0x1

ACL_REVISION = 2

INHERIT_ACE = 0x1 | 0x2

TOKEN_ACCESS: int = (
    win32security.TOKEN_DUPLICATE
    | win32security.TOKEN_QUERY
    | win32security.TOKEN_ASSIGN_PRIMARY
    | win32security.TOKEN_ADJUST_DEFAULT
)


def low_sid() -> Any:
    return win32security.ConvertStringSidToSid(LOW_INTEGRITY_SID)


def restricted_token() -> int:
    source = win32security.OpenProcessToken(win32api.GetCurrentProcess(), TOKEN_ACCESS)

    try:
        token: int = win32security.CreateRestrictedToken(source, DISABLE_MAX_PRIVILEGE, [], [], [])
    finally:
        win32api.CloseHandle(source)

    win32security.SetTokenInformation(
        token, win32security.TokenIntegrityLevel, (low_sid(), SE_GROUP_INTEGRITY)
    )

    return token


def close(handle: int) -> None:
    win32api.CloseHandle(handle)


def token_level(token: int) -> str:
    sid, _attributes = win32security.GetTokenInformation(token, win32security.TokenIntegrityLevel)
    level: str = win32security.ConvertSidToStringSid(sid)

    return level


def apply_label(directory: Path, sid: str | None) -> None:
    sacl = win32security.ACL()

    if sid is not None:
        sacl.AddMandatoryAce(
            ACL_REVISION,
            INHERIT_ACE,
            SYSTEM_MANDATORY_LABEL_NO_WRITE_UP,
            win32security.ConvertStringSidToSid(sid),
        )

    win32security.SetNamedSecurityInfo(
        str(directory), SE_FILE_OBJECT, LABEL_SECURITY_INFORMATION, None, None, None, sacl
    )


def label_low(directory: Path) -> None:
    apply_label(directory, LOW_INTEGRITY_SID)


def label_of(directory: Path) -> str | None:
    descriptor = win32security.GetNamedSecurityInfo(
        str(directory), SE_FILE_OBJECT, LABEL_SECURITY_INFORMATION
    )
    sacl = descriptor.GetSecurityDescriptorSacl()

    if sacl is None:
        return None

    for index in range(sacl.GetAceCount()):
        (ace_type, _flags), _mask, sid = sacl.GetAce(index)

        if ace_type == SYSTEM_MANDATORY_LABEL_ACE_TYPE:
            found: str = win32security.ConvertSidToStringSid(sid)

            return found

    return None


def available() -> bool:
    try:
        token = restricted_token()
    except pywintypes.error:
        return False

    try:
        return token_level(token) == LOW_INTEGRITY_SID
    finally:
        close(token)
