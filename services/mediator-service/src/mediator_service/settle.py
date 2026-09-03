from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from mediator_service import checks
from mediator_service.checks import (
    CheckSpec,
    CheckSpecError,
    FileExists,
    FileHash,
    PortOpen,
)
from mediator_service.dispatch import Result
from mediator_service.upstream import Criterion

VERIFIED: Final[str] = "verified"
FAILED: Final[str] = "failed"

NO_EVIDENCE: Final[str] = "no step in this task produced evidence for this criterion"

LOCAL_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

OBSERVED_ELSEWHERE: Final[frozenset[str]] = frozenset(
    {"http_status", "sql_result", "window_title", "text_on_screen"}
)


@dataclass(frozen=True)
class Verdict:
    criterion_id: str
    status: str | None
    detail: str

    @property
    def settled(self) -> bool:
        return self.status is not None


def normalise(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").casefold()


def rooted(path: str) -> bool:
    if path.startswith("/"):
        return True

    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()


def resolved(path: str, scope_root: str) -> str:
    target = normalise(path)

    while target.startswith("./"):
        target = target[2:]

    if rooted(target):
        return target

    root = normalise(scope_root)

    return f"{root}/{target}" if root else target


def judge_file_exists(spec: FileExists, result: Result, scope_root: str) -> tuple[str | None, str]:
    wanted = resolved(spec.path, scope_root)

    for write in result.files_written:
        if normalise(write.path) == wanted:
            return VERIFIED, f"the run wrote {write.path}"

    return None, f"the run did not write {spec.path}, so whether it exists is unknown here"


def judge_file_hash(spec: FileHash, result: Result, scope_root: str) -> tuple[str | None, str]:
    wanted = resolved(spec.path, scope_root)

    for write in result.files_written:
        if normalise(write.path) != wanted:
            continue

        if write.sha256.casefold() == spec.expected_sha256.casefold():
            return VERIFIED, f"the run wrote {write.path} with the expected digest"

        return (
            FAILED,
            f"the run wrote {write.path} with digest {write.sha256}, "
            f"not the expected {spec.expected_sha256}",
        )

    return None, f"the run did not write {spec.path}, so its digest is unknown here"


def judge_port_open(spec: PortOpen, result: Result, scope_root: str) -> tuple[str | None, str]:
    if spec.host.casefold() not in LOCAL_HOSTS:
        return None, f"port {spec.port} on {spec.host} is not something this run can observe"

    if spec.port in result.ports_opened:
        return VERIFIED, f"the run opened port {spec.port}"

    return None, f"the run did not open port {spec.port}, so whether it is open is unknown here"


def judge(spec: CheckSpec, result: Result, scope_root: str) -> tuple[str | None, str]:
    if isinstance(spec, FileExists):
        return judge_file_exists(spec, result, scope_root)

    if isinstance(spec, FileHash):
        return judge_file_hash(spec, result, scope_root)

    if isinstance(spec, PortOpen):
        return judge_port_open(spec, result, scope_root)

    return None, f"a {spec.TYPE} check is observed by the inspector, not by a run"


def verdict(criterion: Criterion, results: tuple[Result, ...], scope_root: str) -> Verdict:
    if not criterion.mechanisable:
        return Verdict(criterion.id, None, "this criterion is not a deterministic check")

    try:
        spec = checks.parse(criterion.check_spec, "check_spec")
    except CheckSpecError as error:
        return Verdict(criterion.id, None, f"the stored check could not be read: {error.detail}")

    if spec.TYPE in OBSERVED_ELSEWHERE:
        return Verdict(criterion.id, None, f"a {spec.TYPE} check is observed by the inspector")

    outcome: str | None = None
    detail = NO_EVIDENCE

    for result in results:
        found, note = judge(spec, result, scope_root)

        if found is not None:
            outcome = found
            detail = note
        elif outcome is None:
            detail = note

    return Verdict(criterion.id, outcome, detail)


def verdicts(
    criteria: tuple[Criterion, ...], results: tuple[Result, ...], scope_root: str
) -> tuple[Verdict, ...]:
    return tuple(verdict(criterion, results, scope_root) for criterion in criteria)
