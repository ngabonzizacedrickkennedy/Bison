from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class InvalidBlockError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class DuplicateBlockIdError(RuntimeError):
    def __init__(self, block_id: str) -> None:
        super().__init__(f"block id {block_id} appears more than once")
        self.block_id = block_id


def new_block_id() -> str:
    return str(uuid4())


class MarkdownBlock(BaseModel):
    id: str = Field(default_factory=new_block_id)
    type: Literal["markdown"]
    text: str = Field(min_length=1, max_length=100000)


class ImageBlock(BaseModel):
    id: str = Field(default_factory=new_block_id)
    type: Literal["image"]
    material_id: str = Field(min_length=1)
    caption: str | None = Field(default=None, max_length=500)


class LinkBlock(BaseModel):
    id: str = Field(default_factory=new_block_id)
    type: Literal["link"]
    url: str = Field(min_length=1, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)


class ProjectRefBlock(BaseModel):
    id: str = Field(default_factory=new_block_id)
    type: Literal["project_ref"]
    project_id: str = Field(min_length=1)
    note: str | None = Field(default=None, max_length=2000)


class FileRefBlock(BaseModel):
    id: str = Field(default_factory=new_block_id)
    type: Literal["file_ref"]
    material_id: str = Field(min_length=1)
    path: str = Field(min_length=1, max_length=1000)
    note: str | None = Field(default=None, max_length=2000)


ConceiveBlock = Annotated[
    MarkdownBlock | ImageBlock | LinkBlock | ProjectRefBlock | FileRefBlock,
    Field(discriminator="type"),
]

BLOCK_LIST = TypeAdapter(list[ConceiveBlock])

MATERIAL_BLOCKS = (ImageBlock, FileRefBlock)


def parse_blocks(raw: list[dict[str, Any]]) -> list[ConceiveBlock]:
    try:
        blocks = BLOCK_LIST.validate_python(raw)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise InvalidBlockError(f"{location}: {first['msg']}") from error

    seen: set[str] = set()

    for block in blocks:
        if block.id in seen:
            raise DuplicateBlockIdError(block.id)

        seen.add(block.id)

    return blocks


def serialise(blocks: list[ConceiveBlock]) -> list[dict[str, Any]]:
    return [block.model_dump() for block in blocks]


def material_references(blocks: list[ConceiveBlock]) -> list[str]:
    return sorted({block.material_id for block in blocks if isinstance(block, MATERIAL_BLOCKS)})


def project_references(blocks: list[ConceiveBlock]) -> list[str]:
    return sorted({block.project_id for block in blocks if isinstance(block, ProjectRefBlock)})


def unchanged(stored: list[dict[str, Any]], candidate: list[ConceiveBlock]) -> bool:
    return stored == serialise(candidate)
