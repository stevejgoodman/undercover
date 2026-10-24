"""The agent's service: it works the dispatches, evaluations and rounds of
improvement the backend starts, one at a time, resumes a round's improver after a
handler's decision, and picks a claim back up after a handler's sign-off. npm run
dev starts it beside the backend and the dashboard."""

import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel, Field

from agent import api
from agent.client import Refused
from agent.console import describe, show_reports
from agent.dispatcher import work_run
from agent.harness import (
    ClaimAgents,
    carry_on,
    checkpoint_pool,
    claim_agents_of,
    current_claim_agents,
    work_in_run,
)
from agent.improver import (
    Improvement,
    Review,
    RoundStopped,
    carry_on_round,
    new_round,
    record_decision,
    round_number,
    stop_working_rounds,
    work_round,
)

RUNNING = "{what} is running"
RESTART = "A restart"
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
        stop_working_rounds(RESTART)
        yield


app = FastAPI(title="UnderCover Agent", lifespan=lifespan)


class OneThing:
    """The rule that only one dispatch, evaluation or stretch of a round's work runs
    at a time, and what holds it, which a refusal names."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.what = ""

    def take(self, what: str) -> None:
        """Take the rule for some work, or refuse with a 409 naming what holds it."""
        if not self.lock.acquire(blocking=False):
            raise HTTPException(409, RUNNING.format(what=self.what))
        self.what = what

    def name(self, what: str) -> None:
        """Name the work holding the rule, once it is known, such as Dispatch #4."""
        self.what = what

    def release(self) -> None:
        self.what = ""
        self.lock.release()


one_thing = OneThing()
# The claims being resumed after a sign-off, which a dispatch leaves alone.
resuming: set[str] = set()


@app.exception_handler(Refused)
def refused(_: Request, error: Refused) -> JSONResponse:
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


def work_in_background(
    create: Callable[[], dict[str, Any]], claim_agents: ClaimAgents
) -> None:
    """Create a run through the backend and work it, then let the next run start. A
    run whose dispatcher fails is marked stopped."""
    work = partial(work_in_run, new_graph=claim_agents.new_graph)
    try:
        run = create()
        one_thing.name(f"{run['kind'].capitalize()} #{run['number']}")
        work_run(run, work, resuming)
    except Exception:
        log.exception("The run stopped")
        api.stop_runs()
    finally:
        one_thing.release()


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the agent's service is running."""
    return {"status": "ok"}


@app.post("/api/dispatches", operation_id="start_dispatch", status_code=202)
def start_dispatch(
    request: DispatchRequest, claim_agents: ClaimAgentsDep, background: BackgroundTasks
) -> dict[str, str]:
    """Start a dispatch with up to N claim agents at once."""
    one_thing.take("A dispatch")
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
    one_thing.take("An evaluation")
    create = partial(
        api.create_evaluation,
        request.evaluation_set,
        request.tiny,
        claim_agents.setup(request.agents),
    )
    background.add_task(work_in_background, create, claim_agents)
    return ACCEPTED


def build_improvement(request: Request) -> Improvement:
    """Give a round the improver's saver and the claim agents of any version, on the
    service's pool."""
    pool = request.app.state.pool
    return Improvement(PostgresSaver(pool), partial(claim_agents_of, pool=pool))


ImprovementDep = Annotated[Improvement, Depends(build_improvement)]


class RoundRequest(BaseModel):
    handler: str = Field(min_length=1, description="The handler who started it")


class ProposalDecision(BaseModel):
    decision: Review
    reason: str = Field(description="Why, which a rejection needs; or empty")
    handler: str = Field(min_length=1)


def improve(work: Callable[[], None]) -> None:
    """Do a stretch of a round's work, then let the next work start. A round
    stopped by a handler ends its stretch; one whose work fails is stopped with
    the reason."""
    try:
        work()
    except (RoundStopped, Refused) as ended:
        log.info("The round's work ended: %s", ended)
    except Exception as error:
        log.exception("The round's work failed")
        stop_working_rounds(f"An error in the improver: {describe(error)}")
    finally:
        one_thing.release()


def first_stretch(handler: str, improvement: Improvement) -> None:
    """Record a new round and work it up to its first pause for a handler."""
    round = new_round(handler)
    one_thing.name(f"Round {round['number']}")
    work_round(round, improvement)


@app.post("/api/rounds", operation_id="start_round", status_code=202)
def start_round(
    request: RoundRequest, improvement: ImprovementDep, background: BackgroundTasks
) -> dict[str, str]:
    """Start a round of improvement for a handler, without waiting for it."""
    one_thing.take("A round")
    background.add_task(improve, partial(first_stretch, request.handler, improvement))
    return ACCEPTED


@app.post(
    "/api/rounds/{round_id}/proposals/{proposal_id}/decision",
    operation_id="decide_proposal",
    status_code=202,
)
def decide_proposal(
    round_id: str,
    proposal_id: int,
    request: ProposalDecision,
    improvement: ImprovementDep,
    background: BackgroundTasks,
) -> dict[str, str]:
    """Record a handler's decision on a proposal, then resume the improver."""
    one_thing.take(f"Round {round_number(round_id)}")
    decision = request.model_dump()
    try:
        proposal = record_decision(round_id, proposal_id, decision)
    except Exception:
        one_thing.release()
        raise
    work = partial(carry_on_round, round_id, proposal, decision, improvement)
    background.add_task(improve, work)
    return ACCEPTED
