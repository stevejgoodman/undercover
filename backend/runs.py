"""The backend's operations on runs: the dispatches and evaluations the agent's
service works. Only the service writes them, under /api/runs; the dashboard reads
them under /api/dispatches and /api/evaluations."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import Connection, RowMapping, delete, func, insert, select, update

from backend import agent_service, scoring
from backend.auth import SignedIn
from backend.database import (
    LABELED_SETS,
    claim_view,
    claims,
    handler_decisions,
    model_calls,
    now,
    run_claims,
    runs,
    waiting_claim,
    work_times,
)
from backend.dependencies import Database
from backend.lookups import CLAIM_NOT_FOUND, RUN_NOT_FOUND, run_row
from backend.models import (
    Accepted,
    CreateDispatchRequest,
    CreateEvaluationRequest,
    DecisionKind,
    DispatchSummary,
    Evaluation,
    EvaluationSet,
    HeldPayout,
    Run,
    RunClaim,
    RunClaimsRequest,
    RunKind,
    RunStatus,
    ScoredClaim,
    ScoredEvaluation,
    StartDispatchRequest,
    StartEvaluationRequest,
    Status,
)
from backend.views import to_summary

# A copy's id is its original's with the evaluation's number, such as CLM-1104-E7.
COPY_ID = "{claim_id}-E{number}"
# Claims a dispatch left that the next one picks up.
UNFINISHED = {Status.IN_PROGRESS, Status.WAITING}

router = APIRouter()


def claims_of(db: Connection, run_id: str) -> list[RowMapping]:
    """Return the rows of a run's claims, in order, with each one's model cost, its
    seconds of work and the start of its first spell in this run."""
    cost = (
        select(model_calls.c.claim_id, func.sum(model_calls.c.cost).label("cost"))
        .where(model_calls.c.run_id == run_id)
        .group_by(model_calls.c.claim_id)
        .subquery()
    )
    spells = (
        select(
            work_times.c.claim_id,
            func.min(work_times.c.started_at).label("first_started_at"),
            func.sum(work_times.c.seconds).label("seconds"),
        )
        .where(work_times.c.run_id == run_id)
        .group_by(work_times.c.claim_id)
        .subquery()
    )
    query = (
        claim_view.add_columns(
            func.coalesce(cost.c.cost, 0).label("model_cost"),
            spells.c.first_started_at,
            func.coalesce(spells.c.seconds, 0).label("seconds"),
        )
        .join(run_claims, run_claims.c.claim_id == claims.c.claim_id)
        .outerjoin(cost, cost.c.claim_id == claims.c.claim_id)
        .outerjoin(spells, spells.c.claim_id == claims.c.claim_id)
        .where(run_claims.c.run_id == run_id)
        .order_by(run_claims.c.position)
    )
    return list(db.execute(query).mappings())


def to_run_claim(row: RowMapping) -> RunClaim:
    """Build a run's claim: its line in the queue, and its cost and time in the run."""
    return RunClaim(
        **to_summary(row).model_dump(),
        started_at=row["first_started_at"],
        seconds=row["seconds"],
        model_cost=row["model_cost"],
    )


def seconds_between(started_at: str, finished_at: str | None) -> float | None:
    """Return the seconds from a start to a finish, or nothing before the finish."""
    if finished_at is None:
        return None
    start, finish = map(datetime.fromisoformat, (started_at, finished_at))
    return (finish - start).total_seconds()


def cost_and_time(db: Connection, row: RowMapping) -> dict[str, Any]:
    """Return a run's model cost in all, and its seconds once it has finished."""
    total = select(func.coalesce(func.sum(model_calls.c.cost), 0)).where(
        model_calls.c.run_id == row["run_id"]
    )
    return {
        "model_cost": db.execute(total).scalar_one(),
        "seconds": seconds_between(row["started_at"], row["finished_at"]),
    }


def find_run(db: Connection, run_id: str) -> Run:
    """Return one run with its claims, its model cost and its time, or raise a 404."""
    row = run_row(db, run_id)
    return Run(
        **row,
        **cost_and_time(db, row),
        claims=[to_run_claim(claim) for claim in claims_of(db, run_id)],
    )


def running_run(db: Connection, run_id: str) -> RowMapping:
    """Return a run's row if it is still running, or raise a 404 or a 409."""
    row = run_row(db, run_id)
    if row["status"] != RunStatus.RUNNING:
        raise HTTPException(409, f"Run {run_id} is not running")
    return row


def summarize(rows: list[RowMapping]) -> DispatchSummary:
    """Say what a dispatch left, from its claims as they stand, counting each claim
    once: the decisions, with the payouts waiting for a sign-off counted as
    approved, the claims left for a handler, and those the next dispatch picks up."""
    unfinished = [row["claim_id"] for row in rows if row["status"] in UNFINISHED]
    decided = [row for row in rows if row["status"] not in UNFINISHED]
    decisions = [row["decision"] for row in decided]
    return DispatchSummary(
        approved=decisions.count(DecisionKind.APPROVE),
        declined=decisions.count(DecisionKind.DECLINE),
        referred=decisions.count(DecisionKind.REFER),
        waiting_for_sign_off=[
            HeldPayout(claim_id=row["claim_id"], payout=row["payout"])
            for row in rows
            if row["status"] == Status.WAITING_FOR_SIGN_OFF
        ],
        left_for_handler=[
            row["claim_id"] for row in rows if row["status"] == Status.LEFT_FOR_HANDLER
        ],
        unfinished=unfinished,
    )


def new_run(db: Connection, kind: RunKind, fields: dict[str, Any]) -> RowMapping:
    """Record a new run, running, and return its row."""
    run_id = str(uuid.uuid4())
    db.execute(
        insert(runs).values(
            run_id=run_id,
            kind=kind,
            **fields,
            status=RunStatus.RUNNING,
            started_at=now(),
        )
    )
    return run_row(db, run_id)


def put_claims(db: Connection, run_id: str, claim_ids: list[str]) -> None:
    """Record a run's claims in order, in place of any recorded before."""
    db.execute(delete(run_claims).where(run_claims.c.run_id == run_id))
    if claim_ids:
        db.execute(
            insert(run_claims),
            [
                {"run_id": run_id, "position": position, "claim_id": claim_id}
                for position, claim_id in enumerate(claim_ids)
            ],
        )


def originals(
    db: Connection, evaluation_set: EvaluationSet, tiny: bool
) -> list[dict[str, Any]]:
    """Return the records of a labeled set's claims, all or its tiny ones, oldest
    submitted first."""
    chosen = select(handler_decisions.c.claim_id).where(
        handler_decisions.c.evaluation_set == evaluation_set
    )
    if tiny:
        chosen = chosen.where(handler_decisions.c.tiny)
    table = LABELED_SETS[evaluation_set].claims
    records = db.execute(select(table.c.record).where(table.c.claim_id.in_(chosen)))
    return sorted(records.scalars(), key=lambda r: (r["submitted_on"], r["claim_id"]))


def make_copies(
    db: Connection, run: RowMapping, records: list[dict[str, Any]]
) -> list[str]:
    """Copy each claim, waiting, as the evaluation's own, with a new id in its record
    too, and return the copies' ids in order."""
    copies = [
        record
        | {
            "claim_id": COPY_ID.format(
                claim_id=record["claim_id"], number=run["number"]
            )
        }
        for record in records
    ]
    db.execute(
        insert(claims),
        [
            waiting_claim(
                copy, evaluation_id=run["run_id"], copy_of=original["claim_id"]
            )
            for copy, original in zip(copies, records, strict=True)
        ],
    )
    return [copy["claim_id"] for copy in copies]


def evaluation_row(db: Connection, run_id: str) -> RowMapping:
    """Return an evaluation's row, or raise a 404."""
    row = run_row(db, run_id)
    if row["kind"] != RunKind.EVALUATION:
        raise HTTPException(404, RUN_NOT_FOUND.format(run_id=run_id))
    return row


def scored_claim(row: RowMapping, expected: scoring.Answer) -> ScoredClaim:
    """Put an evaluation's copy beside the handler's decision on its original."""
    answer = scoring.answer_of(row["decision"], row["payout"])
    return ScoredClaim(
        **to_run_claim(row).model_dump(),
        copy_of=row["copy_of"],
        reason=row["reason"],
        handler_decision=expected.decision,
        handler_payout=expected.payout,
        right=scoring.is_right(answer, expected),
        mistake_cost=scoring.mistake_cost(answer, expected),
    )


def expected_answers(db: Connection) -> dict[tuple[str, str], scoring.Answer]:
    """Return the handlers' decisions on every labeled claim, by set and claim."""
    rows = db.execute(select(handler_decisions)).mappings()
    return {
        (d["evaluation_set"], d["claim_id"]): scoring.Answer(d["decision"], d["payout"])
        for d in rows
    }


def score(
    db: Connection, row: RowMapping, expected: dict[tuple[str, str], scoring.Answer]
) -> ScoredEvaluation:
    """Score an evaluation from its copies as they stand and the handlers'
    decisions on their originals."""
    scored = [
        scored_claim(claim, expected[row["evaluation_set"], claim["copy_of"]])
        for claim in claims_of(db, row["run_id"])
    ]
    run = cost_and_time(db, row)
    return ScoredEvaluation(
        **row,
        **run,
        size=len(scored),
        measures=scoring.measures(scored, run["model_cost"], run["seconds"]),
        claims=scored,
    )


@router.post("/api/runs/dispatches", operation_id="create_dispatch")
def create_dispatch(request: CreateDispatchRequest, db: Database) -> Run:
    """Record a new dispatch, running, with its claims to come."""
    row = new_run(db, RunKind.DISPATCH, request.model_dump())
    return find_run(db, row["run_id"])


@router.post("/api/runs/evaluations", operation_id="create_evaluation")
def create_evaluation(request: CreateEvaluationRequest, db: Database) -> Run:
    """Record a new evaluation, running, with a waiting copy of each of its claims."""
    row = new_run(db, RunKind.EVALUATION, request.model_dump())
    records = originals(db, request.evaluation_set, request.tiny)
    put_claims(db, row["run_id"], make_copies(db, row, records))
    return find_run(db, row["run_id"])


@router.put("/api/runs/{run_id}/claims", operation_id="record_run_claims")
def record_run_claims(run_id: str, request: RunClaimsRequest, db: Database) -> Run:
    """Record the claims a running dispatch works, in order."""
    if running_run(db, run_id)["kind"] != RunKind.DISPATCH:
        raise HTTPException(409, f"Run {run_id} is not a dispatch")
    known = select(claims.c.claim_id).where(claims.c.claim_id.in_(request.claim_ids))
    missing = set(request.claim_ids) - set(db.execute(known).scalars())
    if missing:
        raise HTTPException(404, CLAIM_NOT_FOUND.format(claim_id=min(missing)))
    put_claims(db, run_id, request.claim_ids)
    return find_run(db, run_id)


@router.post("/api/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: str, db: Database) -> Run:
    """Finish a running run; a dispatch gets its summary from its claims as they are."""
    row = running_run(db, run_id)
    summary = None
    if row["kind"] == RunKind.DISPATCH:
        summary = summarize(claims_of(db, run_id)).model_dump()
    db.execute(
        update(runs)
        .where(runs.c.run_id == run_id)
        .values(status=RunStatus.FINISHED, finished_at=now(), summary=summary)
    )
    return find_run(db, run_id)


@router.post("/api/runs/stop", operation_id="stop_runs")
def stop_runs(db: Database) -> list[str]:
    """Mark every running run stopped, as the agent's service does when it starts."""
    query = (
        update(runs)
        .where(runs.c.status == RunStatus.RUNNING)
        .values(status=RunStatus.STOPPED)
        .returning(runs.c.run_id)
    )
    return list(db.execute(query).scalars())


@router.get("/api/dispatches/latest", operation_id="get_latest_dispatch")
def get_latest_dispatch(db: Database) -> Run | None:
    """Get the newest dispatch with its claims, cost, time and summary, or nothing."""
    query = (
        select(runs.c.run_id)
        .where(runs.c.kind == RunKind.DISPATCH)
        .order_by(runs.c.number.desc())
        .limit(1)
    )
    run_id = db.execute(query).scalar_one_or_none()
    return None if run_id is None else find_run(db, run_id)


@router.post("/api/dispatches", operation_id="start_dispatch", status_code=202)
def start_dispatch(request: StartDispatchRequest, _: SignedIn) -> Accepted:
    """Ask the agent's service to start a dispatch with up to N claim agents at once."""
    agent_service.start_dispatch(request.agents)
    return Accepted()


@router.get("/api/evaluations", operation_id="list_evaluations")
def list_evaluations(db: Database) -> list[Evaluation]:
    """List every evaluation, newest first, with its measures."""
    query = (
        select(runs)
        .where(runs.c.kind == RunKind.EVALUATION)
        .order_by(runs.c.number.desc())
    )
    expected = expected_answers(db)
    return [
        Evaluation(**score(db, row, expected).model_dump(exclude={"claims"}))
        for row in db.execute(query).mappings()
    ]


@router.get("/api/evaluations/{run_id}", operation_id="get_evaluation")
def get_evaluation(run_id: str, db: Database) -> ScoredEvaluation:
    """Get one evaluation with its measures and its claims beside the handlers'."""
    return score(db, evaluation_row(db, run_id), expected_answers(db))


@router.post("/api/evaluations", operation_id="start_evaluation", status_code=202)
def start_evaluation(request: StartEvaluationRequest, _: SignedIn) -> Accepted:
    """Ask the agent's service to start an evaluation with up to N claim agents."""
    agent_service.start_evaluation(request.evaluation_set, request.tiny, request.agents)
    return Accepted()
