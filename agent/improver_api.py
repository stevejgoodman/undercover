"""The UnderCover backend's API as the improver and its rounds use it: one function
for each operation, the service's under /api/runs/rounds and the round as the
dashboard reads it, apart from the claim agent's API so that the claim agent has
no way to the scores or the handlers' decisions."""

from typing import Any, Literal

from agent.client import call

EvaluationSet = Literal["evaluation", "held_out"]
Review = Literal["approve", "reject"]


def round_path(*parts: str | int) -> str:
    """A path under /api/runs/rounds, where the service records a round's work."""
    return "/".join(["/runs/rounds", *map(str, parts)])


def create_round(started_by: str) -> dict[str, Any]:
    return call("POST", round_path(), json={"started_by": started_by})


def get_round(round_id: str) -> dict[str, Any]:
    # The round as the dashboard reads it, which holds nothing from the held-out
    # set but its scores.
    return call("GET", f"/rounds/{round_id}")


def get_improver_instructions(round_id: str) -> dict[str, str]:
    return call("GET", round_path(round_id, "instructions"))


def read_results(round_id: str) -> dict[str, Any]:
    return call("GET", round_path(round_id, "results"))


def start_improving(round_id: str) -> dict[str, Any]:
    return call("POST", round_path(round_id, "improving"))


def record_change_proposal(
    round_id: str, instructions: str, model: str, reasoning_effort: str, reason: str
) -> dict[str, Any]:
    body = {
        "instructions": instructions,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "reason": reason,
    }
    return call("POST", round_path(round_id, "proposals", "changes"), json=body)


def record_recipe_proposal(round_id: str, recipe: str, reason: str) -> dict[str, Any]:
    body = {"recipe": recipe, "reason": reason}
    return call("POST", round_path(round_id, "proposals", "recipes"), json=body)


def record_proposal_decision(
    round_id: str, proposal_id: int, decision: Review, reason: str, handler: str
) -> dict[str, Any]:
    body = {"decision": decision, "reason": reason, "handler": handler}
    path = round_path(round_id, "proposals", proposal_id, "review")
    return call("POST", path, json=body)


def create_version(round_id: str, proposal_id: int) -> dict[str, Any]:
    body = {"proposal_id": proposal_id}
    return call("POST", round_path(round_id, "versions"), json=body)


def create_recipe(round_id: str, proposal_id: int) -> dict[str, Any]:
    body = {"proposal_id": proposal_id}
    return call("POST", round_path(round_id, "recipes"), json=body)


def create_round_evaluation(
    round_id: str,
    evaluation_set: EvaluationSet,
    version: int,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    body = {
        "evaluation_set": evaluation_set,
        "version": version,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }
    return call("POST", round_path(round_id, "evaluations"), json=body)


def record_verdict(round_id: str) -> dict[str, Any]:
    return call("POST", round_path(round_id, "verdict"))


def record_round_model_call(
    round_id: str, input_tokens: int, output_tokens: int, cost: float
) -> dict[str, Any]:
    body = {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost": cost}
    return call("POST", round_path(round_id, "model-calls"), json=body)


def finish_round(round_id: str) -> dict[str, Any]:
    return call("POST", round_path(round_id, "finish"))


def stop_working_rounds(stopped_by: str) -> list[str]:
    return call("POST", round_path("stop"), json={"stopped_by": stopped_by})
