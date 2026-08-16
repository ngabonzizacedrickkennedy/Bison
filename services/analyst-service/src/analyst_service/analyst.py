from __future__ import annotations

from dataclasses import dataclass

from bison_contracts import load_prompt

from analyst_service.analysis import (
    AnalystDraft,
    AnalystParseError,
    Decision,
    decide,
    parse,
)
from analyst_service.broker import BrokerClient
from analyst_service.context import AnalystContext, render

CONTEXT_HEADER = "PROJECT CONTEXT"
CLOSING_INSTRUCTION = "Return the JSON object now, and nothing else."


@dataclass(frozen=True)
class AnalystRun:
    draft: AnalystDraft
    decision: Decision
    model_id: str
    prompt_version: str
    prompt_hash: str
    attempts: int
    repaired: bool


def compose(prompt_text: str, rendered: str) -> str:
    return "\n\n".join(
        [prompt_text.strip(), f"--- {CONTEXT_HEADER} ---", rendered, CLOSING_INSTRUCTION]
    )


def repair_suffix(detail: str) -> str:
    return (
        "Your previous reply could not be read. "
        f"The failure was: {detail}. "
        "Reply again with one JSON object carrying every required key, and nothing else."
    )


async def run(
    client: BrokerClient,
    context: AnalystContext,
    *,
    project_id: str,
    request_id: str,
    prompt_version: str,
    threshold: float,
    budget_chars: int,
    timeout_ms: int,
    repair_attempts: int,
) -> AnalystRun:
    prompt = load_prompt("analyst", prompt_version)
    model_id = await client.binding(project_id)
    rendered = render(context, budget_chars)
    composed = compose(prompt.text, rendered)

    attempts = 0
    failure: AnalystParseError | None = None

    while attempts <= repair_attempts:
        attempts += 1
        instruction = (
            composed if failure is None else f"{composed}\n\n{repair_suffix(failure.detail)}"
        )
        answer = await client.invoke(model_id, instruction, request_id, timeout_ms)

        try:
            draft = parse(answer)
        except AnalystParseError as error:
            failure = error
            continue

        return AnalystRun(
            draft=draft,
            decision=decide(draft, threshold),
            model_id=model_id,
            prompt_version=prompt.version,
            prompt_hash=prompt.hash,
            attempts=attempts,
            repaired=attempts > 1,
        )

    raise failure if failure is not None else AnalystParseError("the analyst returned nothing")
