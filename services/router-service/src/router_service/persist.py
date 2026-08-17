from __future__ import annotations

from dataclasses import asdict
from typing import Any

from router_service.gating import GatedStep
from router_service.router import RouterRun


def step_payload(step: GatedStep) -> dict[str, Any]:
    return {
        "description": step.description,
        "service": step.service,
        "requires_confirmation": step.requires_confirmation,
        "confirmation_reason": step.confirmation_reason,
        "on_failure": step.on_failure,
        "reversible": step.reversible,
        "criterion_refs": list(step.criterion_refs),
        "effects": asdict(step.effects),
    }


def plan_payload(run: RouterRun, request_id: str, scope_root: str) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "scope_root": scope_root,
        "intent": run.plan.intent,
        "rationale": run.plan.rationale,
        "target_engine_id": None,
        "target_model_id": run.model_id,
        "attempts": run.attempts,
        "repaired": run.repaired,
        "model_id": run.model_id,
        "prompt_name": run.prompt_name,
        "prompt_version": run.prompt_version,
        "prompt_hash": run.prompt_hash,
        "steps": [step_payload(step) for step in sorted(run.plan.steps, key=lambda s: s.position)],
    }
