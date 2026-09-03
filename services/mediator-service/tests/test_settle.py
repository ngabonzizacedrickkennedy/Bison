from __future__ import annotations

from typing import Any

from mediator_service.dispatch import FileWrite, Result
from mediator_service.settle import (
    FAILED,
    NO_EVIDENCE,
    VERIFIED,
    normalise,
    resolved,
    rooted,
    verdict,
    verdicts,
)
from mediator_service.upstream import Criterion

SCOPE_ROOT = "C:\\scope"
STEP_ID = "s-1"

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def criterion(
    check_spec: dict[str, Any] | None,
    check_kind: str = "deterministic",
    criterion_id: str = "c-1",
) -> Criterion:
    return Criterion(
        id=criterion_id,
        task_id="t-1",
        statement="the schema file exists",
        check_kind=check_kind,
        check_spec=check_spec,
        weight=1,
        status="unverified",
    )


def result(
    files_written: tuple[FileWrite, ...] = (),
    ports_opened: tuple[int, ...] = (),
    step_id: str = STEP_ID,
) -> Result:
    return Result(
        step_id=step_id,
        state="succeeded",
        exit_code=0,
        terminated_by=None,
        error_message=None,
        files_written=files_written,
        files_deleted=(),
        ports_opened=ports_opened,
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:01+00:00",
    )


def wrote(path: str, sha256: str = DIGEST, size_bytes: int = 12) -> FileWrite:
    return FileWrite(path=path, sha256=sha256, size_bytes=size_bytes)


def file_exists(path: str) -> dict[str, Any]:
    return {"type": "file_exists", "path": path}


def file_hash(path: str, expected: str) -> dict[str, Any]:
    return {"type": "file_hash", "path": path, "expected_sha256": expected}


def port_open(host: str, port: int) -> dict[str, Any]:
    return {"type": "port_open", "host": host, "port": port}


def test_a_backslash_path_and_a_slash_path_normalise_alike() -> None:
    assert normalise("C:\\scope\\schema.sql") == normalise("C:/scope/schema.sql")


def test_case_does_not_survive_normalisation() -> None:
    assert normalise("C:\\Scope\\SCHEMA.SQL") == "c:/scope/schema.sql"


def test_a_trailing_separator_does_not_change_a_path() -> None:
    assert normalise("C:\\scope\\") == "c:/scope"


def test_a_drive_letter_makes_a_path_rooted() -> None:
    assert rooted("c:/scope/schema.sql")


def test_a_leading_slash_makes_a_path_rooted() -> None:
    assert rooted("/srv/schema.sql")


def test_a_bare_name_is_not_rooted() -> None:
    assert not rooted("schema.sql")


def test_a_relative_path_is_anchored_to_the_scope_root() -> None:
    assert resolved("schema.sql", SCOPE_ROOT) == "c:/scope/schema.sql"


def test_a_dot_prefix_is_stripped_before_anchoring() -> None:
    assert resolved("./out/schema.sql", SCOPE_ROOT) == "c:/scope/out/schema.sql"


def test_an_absolute_path_is_left_where_it_points() -> None:
    assert resolved("D:\\elsewhere\\schema.sql", SCOPE_ROOT) == "d:/elsewhere/schema.sql"


def test_a_written_file_verifies_that_it_exists() -> None:
    settled = verdict(
        criterion(file_exists("C:\\scope\\schema.sql")),
        (result((wrote("C:\\scope\\schema.sql"),)),),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED
    assert settled.settled


def test_a_relative_criterion_path_matches_the_absolute_path_the_run_reported() -> None:
    settled = verdict(
        criterion(file_exists("schema.sql")),
        (result((wrote("C:\\scope\\schema.sql"),)),),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED


def test_a_differently_cased_path_still_matches() -> None:
    settled = verdict(
        criterion(file_exists("C:/SCOPE/Schema.SQL")),
        (result((wrote("C:\\scope\\schema.sql"),)),),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED


def test_a_file_the_run_never_touched_is_left_unsettled_rather_than_failed() -> None:
    settled = verdict(
        criterion(file_exists("C:\\scope\\schema.sql")),
        (result((wrote("C:\\scope\\other.txt"),)),),
        SCOPE_ROOT,
    )

    assert settled.status is None
    assert not settled.settled


def test_a_matching_digest_verifies_the_hash() -> None:
    settled = verdict(
        criterion(file_hash("schema.sql", DIGEST)),
        (result((wrote("C:\\scope\\schema.sql", DIGEST),)),),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED


def test_a_digest_reported_in_upper_case_still_matches() -> None:
    settled = verdict(
        criterion(file_hash("schema.sql", DIGEST)),
        (result((wrote("C:\\scope\\schema.sql", DIGEST.upper()),)),),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED


def test_a_wrong_digest_fails_the_criterion() -> None:
    settled = verdict(
        criterion(file_hash("schema.sql", DIGEST)),
        (result((wrote("C:\\scope\\schema.sql", OTHER_DIGEST),)),),
        SCOPE_ROOT,
    )

    assert settled.status == FAILED
    assert OTHER_DIGEST in settled.detail


def test_a_hash_criterion_for_an_untouched_file_stays_unsettled() -> None:
    settled = verdict(
        criterion(file_hash("schema.sql", DIGEST)),
        (result((wrote("C:\\scope\\other.txt"),)),),
        SCOPE_ROOT,
    )

    assert settled.status is None


def test_a_port_the_run_opened_verifies_the_criterion() -> None:
    settled = verdict(
        criterion(port_open("127.0.0.1", 8000)),
        (result(ports_opened=(8000,)),),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED


def test_localhost_is_recognised_as_local() -> None:
    settled = verdict(
        criterion(port_open("localhost", 8000)),
        (result(ports_opened=(8000,)),),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED


def test_a_port_the_run_did_not_open_stays_unsettled() -> None:
    settled = verdict(
        criterion(port_open("127.0.0.1", 8000)),
        (result(ports_opened=(9000,)),),
        SCOPE_ROOT,
    )

    assert settled.status is None


def test_a_port_on_a_remote_host_is_never_verified_from_a_local_run() -> None:
    settled = verdict(
        criterion(port_open("example.test", 8000)),
        (result(ports_opened=(8000,)),),
        SCOPE_ROOT,
    )

    assert settled.status is None
    assert "example.test" in settled.detail


def test_an_http_check_is_left_to_the_inspector() -> None:
    settled = verdict(
        criterion(
            {
                "type": "http_status",
                "url": "http://localhost:8000",
                "expected_status": 200,
                "timeout_ms": 1000,
            }
        ),
        (result(ports_opened=(8000,)),),
        SCOPE_ROOT,
    )

    assert settled.status is None
    assert "inspector" in settled.detail


def test_a_screen_check_is_left_to_the_inspector() -> None:
    settled = verdict(
        criterion({"type": "text_on_screen", "text": "done", "region": None}),
        (result(),),
        SCOPE_ROOT,
    )

    assert settled.status is None
    assert "inspector" in settled.detail


def test_a_judgement_criterion_is_never_settled_from_run_evidence() -> None:
    settled = verdict(
        criterion(file_exists("schema.sql"), check_kind="judgement"),
        (result((wrote("C:\\scope\\schema.sql"),)),),
        SCOPE_ROOT,
    )

    assert settled.status is None
    assert "deterministic" in settled.detail


def test_a_criterion_with_no_stored_check_is_never_settled() -> None:
    settled = verdict(
        criterion(None),
        (result((wrote("C:\\scope\\schema.sql"),)),),
        SCOPE_ROOT,
    )

    assert settled.status is None


def test_a_check_that_cannot_be_read_says_so_rather_than_raising() -> None:
    settled = verdict(
        criterion({"type": "file_exists"}),
        (result((wrote("C:\\scope\\schema.sql"),)),),
        SCOPE_ROOT,
    )

    assert settled.status is None
    assert "could not be read" in settled.detail


def test_a_task_with_no_results_reports_that_nothing_was_observed() -> None:
    settled = verdict(criterion(file_exists("schema.sql")), (), SCOPE_ROOT)

    assert settled.status is None
    assert settled.detail == NO_EVIDENCE


def test_a_later_write_supersedes_an_earlier_one() -> None:
    settled = verdict(
        criterion(file_hash("schema.sql", DIGEST)),
        (
            result((wrote("C:\\scope\\schema.sql", DIGEST),), step_id="s-1"),
            result((wrote("C:\\scope\\schema.sql", OTHER_DIGEST),), step_id="s-2"),
        ),
        SCOPE_ROOT,
    )

    assert settled.status == FAILED


def test_a_later_correction_supersedes_an_earlier_failure() -> None:
    settled = verdict(
        criterion(file_hash("schema.sql", DIGEST)),
        (
            result((wrote("C:\\scope\\schema.sql", OTHER_DIGEST),), step_id="s-1"),
            result((wrote("C:\\scope\\schema.sql", DIGEST),), step_id="s-2"),
        ),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED


def test_a_step_that_touched_nothing_does_not_erase_earlier_evidence() -> None:
    settled = verdict(
        criterion(file_exists("schema.sql")),
        (
            result((wrote("C:\\scope\\schema.sql"),), step_id="s-1"),
            result(step_id="s-2"),
        ),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED


def test_the_criterion_id_is_carried_into_the_verdict() -> None:
    settled = verdict(
        criterion(file_exists("schema.sql"), criterion_id="c-9"),
        (result((wrote("C:\\scope\\schema.sql"),)),),
        SCOPE_ROOT,
    )

    assert settled.criterion_id == "c-9"


def test_every_criterion_gets_a_verdict_in_the_order_it_was_given() -> None:
    settled = verdicts(
        (
            criterion(file_exists("schema.sql"), criterion_id="c-1"),
            criterion(file_hash("schema.sql", OTHER_DIGEST), criterion_id="c-2"),
            criterion(None, criterion_id="c-3"),
        ),
        (result((wrote("C:\\scope\\schema.sql", DIGEST),)),),
        SCOPE_ROOT,
    )

    assert [entry.criterion_id for entry in settled] == ["c-1", "c-2", "c-3"]
    assert [entry.status for entry in settled] == [VERIFIED, FAILED, None]
