"""The UnderCover backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from sqlalchemy import Connection, RowMapping, insert, select, update

from backend import agent_service
from backend.auth import SignedIn
from backend.database import (
    claim_view,
    claims,
    customers,
    decisions,
    engine,
    is_seeded,
    model_calls,
    now,
    payments,
    policies,
    seed,
    settings,
    stamp,
    steps,
    work_times,
)
from backend.dependencies import Database
from backend.documents import contents, search, sections, titles
from backend.lookups import CLAIM_NOT_FOUND, run_row
from backend.models import (
    Claim,
    ClaimSummary,
    DecisionKind,
    DecisionRequest,
    DocumentName,
    FailureRequest,
    Handler,
    Instructions,
    ModelCall,
    ModelCallRequest,
    PaymentRequest,
    Payout,
    PayoutRequest,
    Plans,
    Policy,
    PreviousClaim,
    Section,
    SectionMatch,
    StartRequest,
    Status,
    Step,
    StepRequest,
    WorkTime,
    WorkTimeRequest,
)
from backend.payout import needs_sign_off, work_out_payout
from backend.runs import router
from backend.views import to_claim, to_summary

INSTRUCTIONS = Path(__file__).parent / "instructions"
ATTEMPTS = 2


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed the database on startup if it has no tables yet."""
    if not is_seeded(engine()):
        seed(engine())
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)
app.include_router(router)


def dollars(amount: float) -> str:
    """Format an amount like $1,250.00."""
    return f"${amount:,.2f}"


def approval_limit(db: Connection) -> float:
    """Return the largest payout that can be paid without a handler's sign-off."""
    return db.execute(select(settings.c.payout_approval_limit)).scalar_one()


def plans(db: Connection) -> Plans:
    """Return the plans and add-ons, and the benefits the deductible applies to."""
    return Plans(**db.execute(select(settings.c.plans)).scalar_one())


def find_claim(db: Connection, claim_id: str) -> RowMapping:
    """Return one claim's row, or raise a 404."""
    query = claim_view.where(claims.c.claim_id == claim_id)
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, CLAIM_NOT_FOUND.format(claim_id=claim_id))
    return row


def find_policy(db: Connection, policy_id: str) -> Policy:
    """Return one policy, or raise a 404."""
    query = select(policies.c.record).where(policies.c.policy_id == policy_id)
    record = db.execute(query).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, f"Policy {policy_id} not found")
    return Policy(**record)


def set_status(db: Connection, claim_id: str, status: Status) -> None:
    """Move a claim to a new status."""
    db.execute(
        update(claims).where(claims.c.claim_id == claim_id).values(status=status)
    )


def started_thread(db: Connection, claim_id: str) -> str:
    """Return the thread of a claim that has been started, or raise a 404 or a 409."""
    thread_id = find_claim(db, claim_id)["thread_id"]
    if thread_id is None:
        raise HTTPException(409, f"Claim {claim_id} has not been started")
    return thread_id


def check_run(db: Connection, run_id: str | None) -> None:
    """Check that the run named, if any, exists, or raise a 404."""
    if run_id is not None:
        run_row(db, run_id)


def add_step(
    db: Connection, claim_id: str, thread_id: str, kind: str, content: str
) -> Step:
    """Add one step of the agent's work to a claim."""
    query = (
        insert(steps)
        .values(
            claim_id=claim_id,
            thread_id=thread_id,
            kind=kind,
            content=content,
            created_at=now(),
        )
        .returning(steps)
    )
    return Step(**db.execute(query).mappings().one())


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims(db: Database) -> list[ClaimSummary]:
    """List every claim in the queue, in id order, leaving out evaluations' copies."""
    query = claim_view.where(claims.c.evaluation_id.is_(None))
    rows = db.execute(query.order_by(claims.c.claim_id)).mappings()
    return [to_summary(row) for row in rows]


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, db: Database) -> Claim:
    """Get one claim in full: the story, the items claimed and the documents."""
    return to_claim(find_claim(db, claim_id))


@app.get("/api/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, db: Database) -> Policy:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    return find_policy(db, policy_id)


@app.get("/api/customers/{customer_id}/claims", operation_id="get_claim_history")
def get_claim_history(customer_id: str, db: Database) -> list[PreviousClaim]:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    query = select(customers.c.record).where(customers.c.customer_id == customer_id)
    record = db.execute(query).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, f"Customer {customer_id} not found")
    return [PreviousClaim(**claim) for claim in record["previous_claims"]]


@app.get("/api/instructions", operation_id="get_instructions")
def get_instructions(db: Database) -> Instructions:
    """Get the claim agent's instructions, ending with the documents' contents."""
    claim = (INSTRUCTIONS / "claim.md").read_text(encoding="utf-8")
    return Instructions(claim=f"{claim}\n{contents(db)}")


@app.get("/api/documents/search", operation_id="search_documents")
def search_documents(
    query: Annotated[str, Query(min_length=1)], db: Database
) -> list[SectionMatch]:
    """Find the sections of the wording and the manual that mention a word or phrase."""
    return search(db, query)


@app.get("/api/documents/{document}/sections/{number}", operation_id="read_section")
def read_section(document: DocumentName, number: int, db: Database) -> Section:
    """Read one section of the policy wording or the claims manual in full."""
    for section in sections(db, document):
        if section.number == number:
            return section
    title = titles(db)[document].lower()
    raise HTTPException(404, f"Section {number} of the {title} not found")


@app.get("/api/handlers/me", operation_id="get_signed_in_handler")
def get_signed_in_handler(handler: SignedIn) -> Handler:
    """Get the handler signed in, and whether they can sign off over the limit."""
    return handler


@app.post("/api/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, request: StartRequest, db: Database) -> Claim:
    """Start work on a waiting claim, which moves it to in progress."""
    if find_claim(db, claim_id)["status"] != Status.WAITING:
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    db.execute(
        update(claims)
        .where(claims.c.claim_id == claim_id)
        .values(
            status=Status.IN_PROGRESS,
            thread_id=request.thread_id,
            attempts=claims.c.attempts + 1,
        )
    )
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/steps", operation_id="record_step")
def record_step(claim_id: str, request: StepRequest, db: Database) -> Step:
    """Record one step of the agent's work on a claim."""
    thread_id = started_thread(db, claim_id)
    return add_step(db, claim_id, thread_id, request.kind, request.content)


@app.post("/api/claims/{claim_id}/model-calls", operation_id="record_model_call")
def record_model_call(
    claim_id: str, request: ModelCallRequest, db: Database
) -> ModelCall:
    """Record the tokens and the cost of one model call on a started claim."""
    thread_id = started_thread(db, claim_id)
    check_run(db, request.run_id)
    query = (
        insert(model_calls)
        .values(
            claim_id=claim_id,
            thread_id=thread_id,
            **request.model_dump(),
            created_at=now(),
        )
        .returning(model_calls)
    )
    return ModelCall(**db.execute(query).mappings().one())


@app.post("/api/claims/{claim_id}/work-times", operation_id="record_work_time")
def record_work_time(claim_id: str, request: WorkTimeRequest, db: Database) -> WorkTime:
    """Record one spell of the agent's work on a started claim, ending now."""
    thread_id = started_thread(db, claim_id)
    check_run(db, request.run_id)
    started = datetime.now(UTC) - timedelta(seconds=request.seconds)
    query = (
        insert(work_times)
        .values(
            claim_id=claim_id,
            thread_id=thread_id,
            run_id=request.run_id,
            started_at=stamp(started),
            seconds=request.seconds,
        )
        .returning(work_times)
    )
    return WorkTime(**db.execute(query).mappings().one())


@app.get("/api/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, db: Database) -> list[Step]:
    """List the steps of the agent's work on a claim, in order."""
    find_claim(db, claim_id)
    query = select(steps).where(steps.c.claim_id == claim_id).order_by(steps.c.step_id)
    return [Step(**row) for row in db.execute(query).mappings()]


@app.post("/api/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, request: DecisionRequest, db: Database) -> Claim:
    """Record a claim's decision once; an approval waits to be paid or signed off."""
    claim = find_claim(db, claim_id)
    payout = round(request.payout, 2)
    if claim["decision"] is not None:
        if (claim["decision"], claim["payout"]) == (request.decision, payout):
            return to_claim(claim)
        raise HTTPException(409, f"Claim {claim_id} has already been decided")
    if claim["status"] != Status.IN_PROGRESS:
        raise HTTPException(409, f"Claim {claim_id} is not in progress")
    db.execute(
        insert(decisions).values(
            claim_id=claim_id,
            decision=request.decision,
            payout=payout,
            section=request.section,
            reason=request.reason,
            decided_at=now(),
        )
    )
    if request.decision != DecisionKind.APPROVE:
        set_status(db, claim_id, Status.DECIDED)
    elif needs_sign_off(payout, approval_limit(db)):
        set_status(db, claim_id, Status.WAITING_FOR_SIGN_OFF)
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/payout", operation_id="calculate_payout")
def calculate_payout(claim_id: str, request: PayoutRequest, db: Database) -> Payout:
    """Work out an approval's payout with UnderCover's payout rules; records nothing."""
    policy = find_policy(db, to_claim(find_claim(db, claim_id)).policy_id)
    return work_out_payout(policy, plans(db), request, approval_limit(db))


@app.post("/api/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, request: PaymentRequest, db: Database) -> Claim:
    """Pay an approved claim its payout once, unless it needs a handler's sign-off."""
    claim = find_claim(db, claim_id)
    if claim["decision"] != DecisionKind.APPROVE:
        raise HTTPException(409, f"Claim {claim_id} has not been approved")
    amount = round(request.amount, 2)
    if claim["paid_at"] is not None:
        if amount == claim["amount"]:
            return to_claim(claim)
        raise HTTPException(409, f"Claim {claim_id} has already been paid")
    if claim["status"] == Status.WAITING_FOR_SIGN_OFF:
        raise HTTPException(
            403,
            f"A payout over {dollars(approval_limit(db))} needs a handler's sign-off",
        )
    if amount != claim["payout"]:
        raise HTTPException(
            422, f"The amount must be the approved payout of {dollars(claim['payout'])}"
        )
    db.execute(
        insert(payments).values(
            claim_id=claim_id, amount=claim["payout"], paid_at=now()
        )
    )
    set_status(db, claim_id, Status.DECIDED)
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(
    claim_id: str, handler: SignedIn, db: Database, background: BackgroundTasks
) -> Claim:
    """Sign off a held payout as the handler signed in, so the agent pays it."""
    claim = find_claim(db, claim_id)
    if claim["evaluation_id"] is not None:
        raise HTTPException(
            409, f"Claim {claim_id} is a copy in an evaluation and can't be signed off"
        )
    if claim["status"] != Status.WAITING_FOR_SIGN_OFF:
        raise HTTPException(409, f"Claim {claim_id} is not waiting for sign-off")
    if not handler.can_approve_over_limit:
        raise HTTPException(
            403,
            f"{handler.name} can't sign off payouts over {dollars(approval_limit(db))}",
        )
    db.execute(
        update(decisions)
        .where(decisions.c.claim_id == claim_id)
        .values(signed_off_by=handler.name, signed_off_at=now())
    )
    set_status(db, claim_id, Status.IN_PROGRESS)
    background.add_task(agent_service.resume_claim, claim_id)
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/failure", operation_id="fail_claim")
def fail_claim(claim_id: str, request: FailureRequest, db: Database) -> Claim:
    """Put a failed claim back in the queue, or leave it for a handler after two."""
    claim = find_claim(db, claim_id)
    if claim["status"] != Status.IN_PROGRESS:
        raise HTTPException(409, f"Claim {claim_id} is not in progress")
    if claim["decision"] is not None:
        raise HTTPException(409, f"Claim {claim_id} has already been decided")
    add_step(db, claim_id, claim["thread_id"], "error", request.reason)
    status = (
        Status.LEFT_FOR_HANDLER if claim["attempts"] >= ATTEMPTS else Status.WAITING
    )
    set_status(db, claim_id, status)
    return to_claim(find_claim(db, claim_id))
