from __future__ import annotations

from typing import Any

import pytest

from project_service.conceiveblocks import (
    DuplicateBlockIdError,
    InvalidBlockError,
    material_references,
    parse_blocks,
    project_references,
    serialise,
    unchanged,
)


def markdown(text: str = "a requirement", block_id: str | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "markdown", "text": text}

    if block_id is not None:
        block["id"] = block_id

    return block


def test_every_block_type_is_accepted() -> None:
    blocks = parse_blocks(
        [
            markdown(),
            {"type": "image", "material_id": "m1", "caption": "the sketch"},
            {"type": "link", "url": "https://example.com", "note": "why it matters"},
            {"type": "project_ref", "project_id": "p1"},
            {"type": "file_ref", "material_id": "m1", "path": "repo/src/main.py"},
        ]
    )

    assert [block.type for block in blocks] == [
        "markdown",
        "image",
        "link",
        "project_ref",
        "file_ref",
    ]


def test_order_is_preserved() -> None:
    blocks = parse_blocks([markdown("first"), markdown("second"), markdown("third")])

    assert [serialise(blocks)[index]["text"] for index in range(3)] == [
        "first",
        "second",
        "third",
    ]


def test_missing_id_is_generated_and_unique() -> None:
    blocks = parse_blocks([markdown("one"), markdown("two")])
    identifiers = {block.id for block in blocks}

    assert len(identifiers) == 2
    assert all(block.id for block in blocks)


def test_supplied_id_is_kept() -> None:
    blocks = parse_blocks([markdown("one", block_id="fixed-id")])

    assert blocks[0].id == "fixed-id"


def test_duplicate_ids_are_refused() -> None:
    with pytest.raises(DuplicateBlockIdError):
        parse_blocks([markdown("one", block_id="same"), markdown("two", block_id="same")])


def test_unknown_block_type_is_refused() -> None:
    with pytest.raises(InvalidBlockError):
        parse_blocks([{"type": "video", "url": "https://example.com"}])


def test_empty_markdown_is_refused() -> None:
    with pytest.raises(InvalidBlockError):
        parse_blocks([markdown("")])


def test_image_without_material_is_refused() -> None:
    with pytest.raises(InvalidBlockError):
        parse_blocks([{"type": "image", "caption": "orphan"}])


def test_file_ref_without_path_is_refused() -> None:
    with pytest.raises(InvalidBlockError):
        parse_blocks([{"type": "file_ref", "material_id": "m1"}])


def test_empty_conceive_is_valid() -> None:
    assert parse_blocks([]) == []


def test_material_references_are_collected_without_duplicates() -> None:
    blocks = parse_blocks(
        [
            {"type": "image", "material_id": "m2"},
            {"type": "file_ref", "material_id": "m1", "path": "a.py"},
            {"type": "file_ref", "material_id": "m2", "path": "b.py"},
            {"type": "link", "url": "https://example.com"},
        ]
    )

    assert material_references(blocks) == ["m1", "m2"]


def test_project_references_are_collected() -> None:
    blocks = parse_blocks(
        [{"type": "project_ref", "project_id": "p2"}, {"type": "project_ref", "project_id": "p1"}]
    )

    assert project_references(blocks) == ["p1", "p2"]


def test_round_trip_through_serialise_is_stable() -> None:
    blocks = parse_blocks([markdown("one"), {"type": "link", "url": "https://example.com"}])
    stored = serialise(blocks)

    assert serialise(parse_blocks(stored)) == stored


def test_unchanged_detects_an_identical_save() -> None:
    stored = serialise(parse_blocks([markdown("one", block_id="a")]))
    candidate = parse_blocks([markdown("one", block_id="a")])

    assert unchanged(stored, candidate) is True


def test_unchanged_detects_an_edit() -> None:
    stored = serialise(parse_blocks([markdown("one", block_id="a")]))
    candidate = parse_blocks([markdown("one edited", block_id="a")])

    assert unchanged(stored, candidate) is False


def test_unchanged_detects_reordering() -> None:
    stored = serialise(parse_blocks([markdown("one", block_id="a"), markdown("two", block_id="b")]))
    candidate = parse_blocks([markdown("two", block_id="b"), markdown("one", block_id="a")])

    assert unchanged(stored, candidate) is False
