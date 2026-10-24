"""The agent's service: it works the dispatches and evaluations the backend starts,
one at a time, and picks a claim back up after a handler's sign-off. npm run dev
starts it beside the backend and the dashboard."""

import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent import api
from agent.console import show_reports
from agent.dispatcher import work_run
from agent.harness import (
    ClaimAgents,
    carry_on,
    checkpoint_pool,
    current_claim_agents,
    work_in_run,
)

ALREADY_RUNNING = "A dispatch or an evaluation is already running"
ACCEPTED = {"status": "accepted"}
# The most claim agents at once, as the backend and the dashboard also allow.
MOST_AGENTS = 25

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Keep the checkpoint pool open while the service runs, after marking any run
    an earlier service left running as stopped."""
    show_reports()
    with checkpoint_pool() as pool:
        app.state.pool = pool
        api.stop_runs()
        yield


app = FastAPI(title="UnderCover Agent", lifespan=lifespan)

# One dispatch or evaluation at a time, and the claims being resumed after a
# sign-off, which a dispatch leaves alone.
one_run = threading.Lock()
resuming: set[str] = set()


@app.exception_handler(api.Refused)
def refused(_: Request, error: api.Refused) -> JSONResponse:
    """Pass on the backend's refusal, such as a claim it doesn't know."""
    return JSONResponse({"detail": error.detail}, status_code=error.status_code)


def build_claim_agents(request: Request) -> ClaimAgents:
    """Build the current version's claim agents for one request, on the service's
    pool."""
    return current_claim_agents(request.app.state.pool)


ClaimAgentsDep = Annotated[ClaimAgents, Depends(build_claim_agents)]


class DispatchRequest(BaseModel):
    agents: int = Field(ge=1, le=MOST_AGENTS, description="Claim agents at once")


class EvaluationRequest(DispatchRequest):
    evaluation_set: api.EvaluationSet
    tiny: bool = Field(description="Only the set's five tiny claims")


def take_the_run() -> None:
    """Take the one run the service works at a time, or refuse with a 409."""
    if not one_run.acquire(blocking=False):
        raise HTTPException(409, ALREADY_RUNNING)


def work_in_background(
    create: Callable[[], dict[str, Any]], claim_agents: ClaimAgents
) -> None:
    """Create a run through the backend and work it, then let the next run start. A
    run whose dispatcher fails is marked stopped."""
    work = partial(work_in_run, new_graph=claim_agents.new_graph)
    try:
        work_run(create(), work, resuming)
    except Exception:
        log.exception("The run stopped")
        api.stop_runs()
    finally:
        one_run.release()


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the agent's service is running."""
    return {"status": "ok"}


@app.post("/api/dispatches", operation_id="start_dispatch", status_code=202)
def start_dispatch(
    request: DispatchRequest, claim_agents: ClaimAgentsDep, background: BackgroundTasks
) -> dict[str, str]:
    """Start a dispatch with up to N claim agents at once."""
    take_the_run()
    create = partial(api.create_dispatch, claim_agents.setup(request.agents))
    background.add_task(work_in_background, create, claim_agents)
    return ACCEPTED


def resume(claim_id: str, claim_agents: ClaimAgents) -> None:
    """Carry a signed-off claim on, keeping dispatches away from it meanwhile."""
    try:
        carry_on(claim_id, None, claim_agents.new_graph())
    finally:
        resuming.discard(claim_id)


@app.post("/api/claims/{claim_id}/resume", operation_id="resume_claim", status_code=202)
def resume_claim(
    claim_id: str, claim_agents: ClaimAgentsDep, background: BackgroundTasks
) -> dict[str, str]:
    """Pick a claim back up after a handler's sign-off, without waiting for it."""
    claim = api.get_claim(claim_id)
    signed_off = claim["decision"] and claim["decision"]["signed_off_by"]
    if claim["status"] != api.Status.IN_PROGRESS or not signed_off:
        raise HTTPException(409, f"Claim {claim_id} has no sign-off waiting to be paid")
    resuming.add(claim_id)
    background.add_task(resume, claim_id, claim_agents)
    return ACCEPTED


@app.post("/api/evaluations", operation_id="start_evaluation", status_code=202)
def start_evaluation(
    request: EvaluationRequest,
    claim_agents: ClaimAgentsDep,
    background: BackgroundTasks,
) -> dict[str, str]:
    """Start an evaluation with up to N claim agents at once."""
    take_the_run()
    create = partial(
        api.create_evaluation,
        request.evaluation_set,
        request.tiny,
        claim_agents.setup(request.agents),
    )
    background.add_task(work_in_background, create, claim_agents)
    return ACCEPTED
