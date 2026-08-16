from __future__ import annotations

from dataclasses import dataclass

from bison_contracts import load_prompt

from router_service.broker import BrokerClient
from router_service.context import RouterContext, criterion_ids, render
from router_service.gating import GatedPlan, PlanRejectedError, build
from router_service.plan import RouterParseError, parse

CONTEXT_HEADER = "TASK CONTEXT"
CLOSING_INSTRUCTION = "Return the JSON object now, and nothing else."


@dataclass(frozen=True)
class RouterRun:
    plan: GatedPlan
    model_id: str
    prompt_name: str
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
        "Your previous reply could not be used. "
        f"The failure was: {detail}. "
        "Reply again with one JSON object carrying every required key, and nothing else."
    )


async def run(
    client: BrokerClient,
    context: RouterContext,
    *,
    project_id: str,
    request_id: str,
    prompt_name: str,
    prompt_version: str,
    budget_chars: int,
    timeout_ms: int,
    repair_attempts: int,
) -> RouterRun:
    prompt = load_prompt(prompt_name, prompt_version)
    model_id = await client.binding(project_id)
    rendered = render(context, budget_chars)
    composed = compose(prompt.text, rendered)
    known = criterion_ids(context)

    attempts = 0
    failure: RouterParseError | PlanRejectedError | None = None

    while attempts <= repair_attempts:
        attempts += 1
        instruction = (
            composed if failure is None else f"{composed}\n\n{repair_suffix(failure.detail)}"
        )
        answer = await client.invoke(model_id, instruction, request_id, timeout_ms)

        try:
            gated = build(parse(answer), context.scope_root, known)
        except (RouterParseError, PlanRejectedError) as error:
            failure = error
            continue

        return RouterRun(
            plan=gated,
            model_id=model_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            prompt_hash=prompt.hash,
            attempts=attempts,
            repaired=attempts > 1,
        )

    raise failure if failure is not None else RouterParseError("the router returned nothing")
