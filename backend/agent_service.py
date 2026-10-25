"""The agent's service, as the backend calls it: after each sign-off, to start a
dispatch, an evaluation or a round, and to pass on a decision on a proposal."""

import logging
import os
from http import HTTPStatus
from typing import Any

import httpx
from fastapi import HTTPException

AGENT_URL = os.getenv("UNDERCOVER_AGENT", "http://127.0.0.1:8002")
NOT_RUNNING = "The agent's service isn't running"

agent = httpx.Client(base_url=f"{AGENT_URL}/api", timeout=10)

log = logging.getLogger(__name__)


def resume_claim(claim_id: str) -> None:
    """Ask the agent to pick a claim back up after its sign-off."""
    try:
        agent.post(f"/claims/{claim_id}/resume").raise_for_status()
    except httpx.HTTPError as error:  # the sign-off stands without the agent
        log.warning(
            "The agent didn't pick up %s after its sign-off: %s", claim_id, error
        )


def start(path: str, body: dict[str, Any]) -> None:
    """Ask the agent's service to start some work, passing on its refusal while
    something else is running, or say it isn't running when it can't be reached."""
    try:
        response = agent.post(path, json=body)
    except (httpx.ConnectError, httpx.ConnectTimeout) as error:
        raise HTTPException(HTTPStatus.SERVICE_UNAVAILABLE, NOT_RUNNING) from error
    if response.status_code == HTTPStatus.CONFLICT:
        raise HTTPException(HTTPStatus.CONFLICT, response.json()["detail"])
    response.raise_for_status()


def start_dispatch(agents: int) -> None:
    """Ask the agent's service to start a dispatch with up to N claim agents."""
    start("/dispatches", {"agents": agents})


def start_evaluation(evaluation_set: str, tiny: bool, agents: int) -> None:
    """Ask the agent's service to start an evaluation with up to N claim agents."""
    body = {"evaluation_set": evaluation_set, "tiny": tiny, "agents": agents}
    start("/evaluations", body)


def start_round(handler: str) -> None:
    """Ask the agent's service to start a round of improvement for a handler."""
    start("/rounds", {"handler": handler})


def decide_proposal(
    round_id: str, proposal_id: int, decision: str, reason: str, handler: str
) -> None:
    """Pass a handler's approval or rejection of a proposal to the agent's service,
    which records it and resumes the improver."""
    body = {"decision": decision, "reason": reason, "handler": handler}
    start(f"/rounds/{round_id}/proposals/{proposal_id}/decision", body)
