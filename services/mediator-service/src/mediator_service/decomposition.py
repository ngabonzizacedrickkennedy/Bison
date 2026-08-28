from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from bison_contracts import load_prompt

from mediator_service.broker import ENGINE_ROLE, MEDIATOR_ROLE, BrokerClient
from mediator_service.context import MediatorContext, render
from mediator_service.discipline import TreeRejectedError, assert_disciplined
from mediator_service.sequencing import Node, Ordering, SequencingError, build
from mediator_service.tree import MediatorParseError, TreeDraft, parse

CONTEXT_HEADER: Final[str] = "PROJECT CONTEXT"
CLOSING_INSTRUCTION: Final[str] = "Return the JSON object now, and nothing else."

APPROACH_INSTRUCTION: Final[str] = (
    "Describe in prose how you would carry this out on this machine. "
    "Name the pieces of work and the order they depend on. Do not return JSON."
)


@dataclass(frozen=True)
class PromptRecord:
    name: str
    version: str
    hash: str


@dataclass(frozen=True)
class Decomposition:
    draft: TreeDraft
    ordering: Ordering
    approach: str
    engine_model_id: str
    mediator_model_id: str
    engine_prompt: PromptRecord
    mediator_prompt: PromptRecord
    attempts: int
    repaired: bool


def compose(prompt_text: str, rendered: str, closing: str) -> str:
    return "\n\n".join([prompt_text.strip(), f"--- {CONTEXT_HEADER} ---", rendered, closing])


def repair_suffix(details: tuple[str, ...]) -> str:
    listed = " ".join(f"({index + 1}) {item}." for index, item in enumerate(details))

    return (
        "Your previous reply could not be used. "
        f"The problems were: {listed} "
        "Reply again with one JSON object carrying every required key, and nothing else."
    )


def failures(error: MediatorParseError | TreeRejectedError | SequencingError) -> tuple[str, ...]:
    if isinstance(error, TreeRejectedError):
        return error.findings

    return (error.detail,)


def nodes(draft: TreeDraft) -> list[Node]:
    return [
        Node(
            id=task.ref,
            parent_id=task.parent_ref,
            depends_on=task.depends_on,
            position=task.position,
        )
        for task in draft.tasks
    ]


async def run(
    client: BrokerClient,
    context: MediatorContext,
    *,
    project_id: str,
    request_id: str,
    engine_prompt_name: str,
    engine_prompt_version: str,
    mediator_prompt_name: str,
    mediator_prompt_version: str,
    budget_chars: int,
    timeout_ms: int,
    repair_attempts: int,
) -> Decomposition:
    engine_prompt = load_prompt(engine_prompt_name, engine_prompt_version)
    mediator_prompt = load_prompt(mediator_prompt_name, mediator_prompt_version)

    bound = await client.bindings(project_id)
    engine_model_id = BrokerClient.binding_for(bound, ENGINE_ROLE)
    mediator_model_id = BrokerClient.binding_for(bound, MEDIATOR_ROLE)

    approach = await client.approach(
        engine_model_id,
        compose(engine_prompt.text, render(context, budget_chars), APPROACH_INSTRUCTION),
        request_id,
        timeout_ms,
    )

    rendered = render(context, budget_chars, approach)
    composed = compose(mediator_prompt.text, rendered, CLOSING_INSTRUCTION)

    attempts = 0
    failure: MediatorParseError | TreeRejectedError | SequencingError | None = None

    while attempts <= repair_attempts:
        attempts += 1
        instruction = (
            composed if failure is None else f"{composed}\n\n{repair_suffix(failures(failure))}"
        )
        answer = await client.tree(mediator_model_id, instruction, request_id, timeout_ms)

        try:
            draft = parse(answer)
            assert_disciplined(draft)
            ordering = build(nodes(draft))
        except (MediatorParseError, TreeRejectedError, SequencingError) as error:
            failure = error
            continue

        return Decomposition(
            draft=draft,
            ordering=ordering,
            approach=approach,
            engine_model_id=engine_model_id,
            mediator_model_id=mediator_model_id,
            engine_prompt=PromptRecord(
                name=engine_prompt.name,
                version=engine_prompt.version,
                hash=engine_prompt.hash,
            ),
            mediator_prompt=PromptRecord(
                name=mediator_prompt.name,
                version=mediator_prompt.version,
                hash=mediator_prompt.hash,
            ),
            attempts=attempts,
            repaired=attempts > 1,
        )

    raise failure if failure is not None else MediatorParseError("the mediator returned nothing")
