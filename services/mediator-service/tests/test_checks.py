from __future__ import annotations

from typing import Any

import pytest

from mediator_service.checks import (
    CheckSpecError,
    FileExists,
    FileHash,
    HttpStatus,
    PortOpen,
    Region,
    SqlResult,
    TextOnScreen,
    WindowTitle,
    parse,
    payload,
)

LABEL = "tasks[2].criteria[0].check_spec"
DIGEST = "a" * 64


def spec(**fields: Any) -> dict[str, Any]:
    return dict(fields)


def test_a_file_exists_check_parses() -> None:
    result = parse(spec(type="file_exists", path=r"C:\work\out.txt"), LABEL)

    assert result == FileExists(path=r"C:\work\out.txt")


def test_a_port_open_check_parses() -> None:
    result = parse(spec(type="port_open", host="127.0.0.1", port=5432), LABEL)

    assert result == PortOpen(host="127.0.0.1", port=5432)


def test_an_http_status_check_parses() -> None:
    result = parse(
        spec(
            type="http_status",
            url="http://127.0.0.1:8000/health",
            expected_status=200,
            timeout_ms=2000,
        ),
        LABEL,
    )

    assert result == HttpStatus(
        url="http://127.0.0.1:8000/health", expected_status=200, timeout_ms=2000
    )


def test_a_sql_result_check_parses() -> None:
    result = parse(
        spec(
            type="sql_result",
            connection_ref="bison_dev",
            query="select 1 from users",
            expect="row_count > 0",
        ),
        LABEL,
    )

    assert result == SqlResult(
        connection_ref="bison_dev", query="select 1 from users", expect="row_count > 0"
    )


def test_a_window_title_check_parses() -> None:
    assert parse(spec(type="window_title", pattern="Settings"), LABEL) == WindowTitle(
        pattern="Settings"
    )


def test_a_text_on_screen_check_parses_without_a_region() -> None:
    result = parse(spec(type="text_on_screen", text="Account deleted", region=None), LABEL)

    assert result == TextOnScreen(text="Account deleted", region=None)


def test_a_text_on_screen_check_parses_with_a_region() -> None:
    result = parse(
        spec(
            type="text_on_screen",
            text="Account deleted",
            region={"x": 0, "y": 10, "width": 400, "height": 200},
        ),
        LABEL,
    )

    assert result == TextOnScreen(
        text="Account deleted", region=Region(x=0, y=10, width=400, height=200)
    )


def test_a_missing_region_is_treated_as_absent() -> None:
    result = parse(spec(type="text_on_screen", text="Done"), LABEL)

    assert result == TextOnScreen(text="Done", region=None)


def test_a_process_exit_check_is_refused_with_its_reason() -> None:
    with pytest.raises(CheckSpecError) as caught:
        parse(spec(type="process_exit", step_id="s1", expected_code=0), LABEL)

    assert "no step exists" in caught.value.detail


def test_an_unknown_check_type_lists_the_ones_that_work() -> None:
    with pytest.raises(CheckSpecError) as caught:
        parse(spec(type="vibes", path="x"), LABEL)

    assert "file_exists" in caught.value.detail
    assert "sql_result" in caught.value.detail


def test_a_missing_check_type_is_refused() -> None:
    with pytest.raises(CheckSpecError):
        parse(spec(path=r"C:\work\out.txt"), LABEL)


def test_a_check_spec_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(CheckSpecError):
        parse("file_exists", LABEL)


def test_a_placeholder_hash_is_refused_but_a_real_one_is_accepted() -> None:
    with pytest.raises(CheckSpecError) as caught:
        parse(
            spec(type="file_hash", path="setup.exe", expected_sha256="<sha256 of the file>"),
            LABEL,
        )

    assert "placeholder" in caught.value.detail

    accepted = parse(spec(type="file_hash", path="setup.exe", expected_sha256=DIGEST), LABEL)

    assert accepted == FileHash(path="setup.exe", expected_sha256=DIGEST)


def test_a_hash_is_normalised_to_lower_case() -> None:
    result = parse(spec(type="file_hash", path="setup.exe", expected_sha256=DIGEST.upper()), LABEL)

    assert result == FileHash(path="setup.exe", expected_sha256=DIGEST)


def test_a_hash_of_the_wrong_length_is_refused() -> None:
    with pytest.raises(CheckSpecError):
        parse(spec(type="file_hash", path="setup.exe", expected_sha256="abc123"), LABEL)


def test_a_boolean_is_not_accepted_as_a_number() -> None:
    with pytest.raises(CheckSpecError):
        parse(spec(type="port_open", host="127.0.0.1", port=True), LABEL)


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_a_port_outside_the_legal_range_is_refused(port: int) -> None:
    with pytest.raises(CheckSpecError):
        parse(spec(type="port_open", host="127.0.0.1", port=port), LABEL)


@pytest.mark.parametrize("port", [1, 65535])
def test_the_edges_of_the_port_range_are_accepted(port: int) -> None:
    assert parse(spec(type="port_open", host="127.0.0.1", port=port), LABEL) == PortOpen(
        host="127.0.0.1", port=port
    )


@pytest.mark.parametrize("status", [99, 600])
def test_an_impossible_http_status_is_refused(status: int) -> None:
    with pytest.raises(CheckSpecError):
        parse(
            spec(type="http_status", url="http://x", expected_status=status, timeout_ms=1000),
            LABEL,
        )


def test_a_timeout_of_zero_is_refused() -> None:
    with pytest.raises(CheckSpecError):
        parse(
            spec(type="http_status", url="http://x", expected_status=200, timeout_ms=0),
            LABEL,
        )


def test_a_region_with_no_area_is_refused() -> None:
    with pytest.raises(CheckSpecError):
        parse(
            spec(
                type="text_on_screen",
                text="Done",
                region={"x": 0, "y": 0, "width": 0, "height": 10},
            ),
            LABEL,
        )


def test_a_region_off_the_top_left_of_the_screen_is_refused() -> None:
    with pytest.raises(CheckSpecError):
        parse(
            spec(
                type="text_on_screen",
                text="Done",
                region={"x": -1, "y": 0, "width": 10, "height": 10},
            ),
            LABEL,
        )


def test_a_region_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(CheckSpecError):
        parse(spec(type="text_on_screen", text="Done", region="whole screen"), LABEL)


def test_a_blank_string_is_not_a_value() -> None:
    with pytest.raises(CheckSpecError):
        parse(spec(type="file_exists", path="   "), LABEL)


def test_surrounding_whitespace_is_stripped() -> None:
    assert parse(spec(type="file_exists", path="  out.txt  "), LABEL) == FileExists(path="out.txt")


def test_every_failure_names_the_field_it_came_from() -> None:
    with pytest.raises(CheckSpecError) as caught:
        parse(spec(type="port_open", host="", port=80), LABEL)

    assert caught.value.detail.startswith(f"{LABEL}.host")


def test_a_payload_carries_the_type_and_nothing_hidden() -> None:
    assert payload(FileExists(path="out.txt")) == {"type": "file_exists", "path": "out.txt"}
    assert payload(PortOpen(host="127.0.0.1", port=5432)) == {
        "type": "port_open",
        "host": "127.0.0.1",
        "port": 5432,
    }


def test_a_payload_flattens_a_nested_region() -> None:
    spec_with_region = TextOnScreen(text="Done", region=Region(x=1, y=2, width=3, height=4))

    assert payload(spec_with_region) == {
        "type": "text_on_screen",
        "text": "Done",
        "region": {"x": 1, "y": 2, "width": 3, "height": 4},
    }
