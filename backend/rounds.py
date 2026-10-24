"""The backend's operations on rounds of improvement, their proposals and the
recipe's versions. Senior handlers start and stop rounds and decide proposals on
the dashboard, under /api/rounds; the agent's service records a round's work under
/api/runs/rounds, each write only in the stage it belongs to, and the backend
keeps or rolls back each version by the rule."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import Connection, RowMapping, func, insert, select, update

from backend import agent_service, improver_view, spending, verdict
from backend.auth import Senior
from backend.database import (
    INSTRUCTIONS,
    agent_versions,
    handler_decisions,
    now,
    proposals,
    recipes,
    round_model_calls,
    rounds,
    runs,
)
from backend.dependencies import Database
from backend.diffs import diff
from backend.lookups import (
    current_settings,
    current_version,
    find_version,
    models_allowed,
    round_left,
    round_row,
    round_settings,
)
from backend.models import (
    Accepted,
    AgentVersion,
    AllowedModel,
    ChangeProposalRequest,
    CreateRoundRequest,
    EvaluationSet,
    FromProposalRequest,
    ImproverInstructions,
    ImproverResults,
    Progress,
    Proposal,
    ProposalKind,
    ProposalStatus,
    Recipe,
    RecipeProposalRequest,
    RecordReviewRequest,
    Review,
    ReviewRequest,
    Round,
    RoundDetails,
    RoundEvaluationRequest,
    RoundModelCallRequest,
    RoundStage,
    Run,
    RunKind,
    RunStatus,
    Scores,
    VersionVerdict,
)
from backend.new_runs import new_evaluation
from backend.run_views import expected_answers, find_run, version_scores

# Rounds the service is working, and rounds waiting for a handler. A restart
# stops the first and keeps the second.
WORKING = {
    RoundStage.FIRST_EVALUATIONS,
    RoundStage.IMPROVING,
    RoundStage.EVALUATIONS,
    RoundStage.VERDICT,
}
WAITING = {RoundStage.WAITING_FOR_CHANGE, RoundStage.WAITING_FOR_RECIPE}
OPEN = WORKING | WAITING
# The evaluations a version needs from rounds before a round compares with it,
# which are also the ones a new version gets: one of the evaluation set and two
# held out.
EVALUATIONS_NEEDED = {EvaluationSet.EVALUATION: 1, EvaluationSet.HELD_OUT: 2}
ALL_EVALUATIONS = sum(EVALUATIONS_NEEDED.values())
FINISHED = {RunStatus.FINISHED}
STARTED = {RunStatus.FINISHED, RunStatus.RUNNING}
RESTART = "A restart"
ROUND_CLOSED = "Round {number} is {stage}"
NOT_NOW = "Round {number} is at the {stage} stage, so it can't {what}"
OPEN_ROUND = "Round {number} is open, and only one round is open at a time"
PROPOSAL_NOT_FOUND = "Proposal {proposal_id} not found"
PROPOSED_BY = "The improver, round {number}"
ENDED_BEFORE_VERDICT = "the round ended before its verdict"

router = APIRouter()


# Finding rounds and what they hold


def round_still_open(db: Connection, round_id: str) -> RowMapping:
    """Return an open round's row, or raise a 404, or a 409 for a round that is
    stopped or finished, which records nothing more."""
    row = round_row(db, round_id)
    if row["stage"] not in OPEN:
        detail = ROUND_CLOSED.format(number=row["number"], stage=row["stage"])
        raise HTTPException(409, detail)
    return row


def require_stage(row: RowMapping, what: str, *stages: RoundStage) -> None:
    """Refuse a write that doesn't belong to the stage the round is at."""
    if row["stage"] not in stages:
        stage = row["stage"].replace("_", " ")
        detail = NOT_NOW.format(number=row["number"], stage=stage, what=what)
        raise HTTPException(409, detail)


def find_open_round(db: Connection) -> RowMapping | None:
    """Return the round that's open, if any."""
    query = select(rounds).where(rounds.c.stage.in_(OPEN))
    return db.execute(query).mappings().first()


def models_of(row: RowMapping) -> list[AllowedModel]:
    """The models a round may propose, as they stood when it started."""
    return [AllowedModel(**model) for model in row["models_allowed"]]


def evaluations_of(db: Connection, version: int) -> list[RowMapping]:
    """Return the whole-set evaluations rounds ran on a version, oldest first."""
    query = select(runs).where(
        runs.c.kind == RunKind.EVALUATION,
        runs.c.version == version,
        runs.c.round_id.is_not(None),
        runs.c.tiny.is_(False),
    )
    return list(db.execute(query.order_by(runs.c.number)).mappings())


def evaluations_missing(
    db: Connection, version: int, counting: set[RunStatus]
) -> list[EvaluationSet]:
    """Return the evaluations a version still needs, one of the evaluation set and
    two held out, counting the runs with the statuses given."""
    counted = [
        run["evaluation_set"]
        for run in evaluations_of(db, version)
        if run["status"] in counting
    ]
    return [
        evaluation_set
        for evaluation_set, needed in EVALUATIONS_NEEDED.items()
        for _ in range(max(0, needed - counted.count(evaluation_set)))
    ]


def progress(db: Connection, row: RowMapping) -> Progress | None:
    """How many of a round's evaluations have started, in the stages that run
    them."""
    if row["stage"] == RoundStage.FIRST_EVALUATIONS:
        version = row["version_before"]
    elif row["stage"] == RoundStage.EVALUATIONS:
        version = row["version_tried"]
    else:
        return None
    missing = evaluations_missing(db, version, STARTED)
    return Progress(done=ALL_EVALUATIONS - len(missing), of=ALL_EVALUATIONS)


def to_round(db: Connection, row: RowMapping, spent: dict[str, float]) -> Round:
    """Build a round as the API shows it, with its progress and what it cost."""
    fields = {name: row[name] for name in Round.model_fields if name in row}
    return Round(
        **fields,
        progress=progress(db, row),
        cost=spent.get(row["round_id"], 0.0),
        spending_limit=round_settings(row).spending_limit,
    )


def one_round(db: Connection, round_id: str) -> Round:
    return to_round(db, round_row(db, round_id), spending.spent_by_round(db))


def to_proposal(
    row: RowMapping, versions: dict[int, RowMapping], recipe_texts: dict[int, str]
) -> Proposal:
    """Build a proposal with what it would change from what it was proposed
    against."""
    fields = {name: row[name] for name in Proposal.model_fields if name in row}
    if row["kind"] == ProposalKind.CHANGE:
        before = versions[row["based_on"]]
        return Proposal(
            **fields,
            model_before=before["model"],
            reasoning_effort_before=before["reasoning_effort"],
            diff=diff(before["instructions"], row["instructions"]),
        )
    return Proposal(
        **fields,
        model_before=None,
        reasoning_effort_before=None,
        diff=diff(recipe_texts[row["based_on"]], row["recipe"]),
    )


def proposals_of(db: Connection, round_id: str) -> list[Proposal]:
    """A round's proposals, oldest first, with what they were proposed against
    loaded with one query for each kind."""
    query = (
        select(proposals)
        .where(proposals.c.round_id == round_id)
        .order_by(proposals.c.proposal_id)
    )
    rows = list(db.execute(query).mappings())
    bases = [row["based_on"] for row in rows]
    versions = db.execute(
        select(agent_versions).where(agent_versions.c.version.in_(bases))
    ).mappings()
    texts = db.execute(
        select(recipes.c.version, recipes.c.recipe).where(recipes.c.version.in_(bases))
    ).mappings()
    by_version = {v["version"]: v for v in versions}
    by_recipe = {t["version"]: t["recipe"] for t in texts}
    return [to_proposal(row, by_version, by_recipe) for row in rows]


def find_proposal(db: Connection, row: RowMapping, proposal_id: int) -> RowMapping:
    """Return one of a round's proposals, or raise a 404."""
    query = select(proposals).where(
        proposals.c.proposal_id == proposal_id,
        proposals.c.round_id == row["round_id"],
    )
    proposal = db.execute(query).mappings().first()
    if proposal is None:
        raise HTTPException(404, PROPOSAL_NOT_FOUND.format(proposal_id=proposal_id))
    return proposal


def proposal_with_status(
    db: Connection, row: RowMapping, proposal_id: int, status: ProposalStatus
) -> RowMapping:
    """Return a round's proposal if it has the status given, or raise a 409."""
    proposal = find_proposal(db, row, proposal_id)
    if proposal["status"] != status:
        raise HTTPException(409, f"Proposal {proposal_id} is {proposal['status']}")
    return proposal


def newest_recipe(db: Connection) -> int:
    return db.execute(select(func.max(recipes.c.version))).scalar_one()


def recipe_text(db: Connection, version: int) -> str:
    query = select(recipes.c.recipe).where(recipes.c.version == version)
    return db.execute(query).scalar_one()


def round_details(db: Connection, round_id: str) -> RoundDetails:
    row = round_row(db, round_id)
    return RoundDetails(
        **one_round(db, round_id).model_dump(),
        settings=round_settings(row),
        models_allowed=models_of(row),
        first_evaluations_missing=evaluations_missing(
            db, row["version_before"], FINISHED
        ),
        proposals=proposals_of(db, round_id),
    )


# Writing rounds


def set_round(db: Connection, round_id: str, **values: Any) -> None:
    db.execute(update(rounds).where(rounds.c.round_id == round_id).values(**values))


def set_verdict(db: Connection, version: int, outcome: VersionVerdict) -> None:
    db.execute(
        update(agent_versions)
        .where(agent_versions.c.version == version)
        .values(verdict=outcome)
    )


def close(db: Connection, row: RowMapping, stage: RoundStage, **values: Any) -> None:
    """Finish or stop a round. A version it was trying with no verdict yet is
    rolled back, so the current version stays as it was, and a proposal still
    waiting is rejected."""
    if row["version_tried"] is not None and row["verdict"] is None:
        set_verdict(db, row["version_tried"], VersionVerdict.ROLLED_BACK)
        values |= {"verdict": VersionVerdict.ROLLED_BACK, "why": ENDED_BEFORE_VERDICT}
    db.execute(
        update(proposals)
        .where(
            proposals.c.round_id == row["round_id"],
            proposals.c.status == ProposalStatus.WAITING,
        )
        .values(
            status=ProposalStatus.REJECTED,
            decided_at=now(),
            rejection=f"The round was {stage}",
        )
    )
    set_round(db, row["round_id"], stage=stage, finished_at=now(), **values)


def stop(db: Connection, row: RowMapping, stopped_by: str) -> None:
    """Stop a round and its running evaluation."""
    db.execute(
        update(runs)
        .where(runs.c.round_id == row["round_id"], runs.c.status == RunStatus.RUNNING)
        .values(status=RunStatus.STOPPED)
    )
    close(db, row, RoundStage.STOPPED, stopped_by=stopped_by)


def check_allowed(row: RowMapping, model: str, reasoning_effort: str) -> None:
    """Refuse a model or a reasoning effort outside the round's models allowed."""
    for allowed in models_of(row):
        if allowed.model == model and reasoning_effort in allowed.reasoning_efforts:
            return
    raise HTTPException(
        422, f"{model} at {reasoning_effort} isn't one of the models allowed"
    )


def describe_change(before: AgentVersion, proposal: RowMapping) -> str:
    """Say in a few words what a version changes from the one before."""
    changed = [
        label
        for label, field in (
            ("Instructions", "instructions"),
            ("Model", "model"),
            ("Reasoning effort", "reasoning_effort"),
        )
        if getattr(before, field) != proposal[field]
    ]
    return " and ".join(changed).capitalize() if changed else "No change"


def add_proposal(
    db: Connection, row: RowMapping, kind: ProposalKind, **fields: Any
) -> Proposal:
    """Record a proposal waiting for a handler, and the round waiting with it."""
    stage = (
        RoundStage.WAITING_FOR_CHANGE
        if kind == ProposalKind.CHANGE
        else RoundStage.WAITING_FOR_RECIPE
    )
    db.execute(
        insert(proposals).values(
            round_id=row["round_id"],
            kind=kind,
            status=ProposalStatus.WAITING,
            created_at=now(),
            **fields,
        )
    )
    set_round(db, row["round_id"], stage=stage)
    return proposals_of(db, row["round_id"])[-1]


def check_evaluation_needed(
    db: Connection, row: RowMapping, request: RoundEvaluationRequest
) -> None:
    """Refuse an evaluation the round doesn't need: the current version's first
    evaluations while they're missing, and the version tried's three before its
    verdict, each set no more often than it needs."""
    version = None
    if row["stage"] == RoundStage.FIRST_EVALUATIONS:
        version = row["version_before"]
    elif row["version_tried"] is not None and row["verdict"] is None:
        version = row["version_tried"]
    needed = [] if version is None else evaluations_missing(db, version, STARTED)
    if request.version != version or request.evaluation_set not in needed:
        raise HTTPException(
            409,
            f"Round {row['number']} doesn't need an evaluation of the "
            f"{request.evaluation_set} set on version {request.version}",
        )


def check_affordable(
    db: Connection, row: RowMapping, request: RoundEvaluationRequest
) -> None:
    """Refuse an evaluation that would likely cost more than what's left, or any
    once the round has spent its limit."""
    size = db.execute(
        select(func.count()).where(
            handler_decisions.c.evaluation_set == request.evaluation_set
        )
    ).scalar_one()
    current = find_version(db, row["version_before"]).model
    likely = spending.estimate(db, size, request.model, current, models_of(row))
    left = round_left(db, row)
    if left <= 0 or likely > left:
        raise HTTPException(
            402,
            f"The evaluation could cost about ${likely:.2f}, and "
            f"${max(left, 0):.2f} of the round's limit is left",
        )


def decide(db: Connection, row: RowMapping, after: Scores | None) -> verdict.Verdict:
    """Keep or roll back the version a round tried, by the rule, unless its
    evaluations were stopped or it couldn't afford them all."""
    tried = evaluations_of(db, row["version_tried"])
    if any(run["status"] == RunStatus.STOPPED for run in tried):
        return verdict.Verdict(False, "its evaluations were stopped")
    if after is None or evaluations_missing(db, row["version_tried"], FINISHED):
        return verdict.Verdict(False, "the round couldn't afford to evaluate it")
    settings = round_settings(row)
    return verdict.keep_or_roll_back(
        after,
        Scores(**row["scores_before"]),
        settings.objectives,
        settings.noise,
        settings.tolerance,
    )


# The dashboard's operations


@router.get("/api/rounds", operation_id="list_rounds")
def list_rounds(db: Database) -> list[Round]:
    """List every round, newest first, with its stage, scores, verdict and cost."""
    query = select(rounds).order_by(rounds.c.number.desc())
    spent = spending.spent_by_round(db)
    return [to_round(db, row, spent) for row in db.execute(query).mappings()]


@router.get("/api/rounds/{round_id}", operation_id="get_round")
def get_round(round_id: str, db: Database) -> RoundDetails:
    """Get a round with its settings, its proposals and what each would change."""
    return round_details(db, round_id)


@router.post("/api/rounds", operation_id="start_round", status_code=202)
def start_round(handler: Senior, db: Database) -> Accepted:
    """Ask the agent's service to start a round, as a senior handler."""
    if (row := find_open_round(db)) is not None:
        raise HTTPException(409, OPEN_ROUND.format(number=row["number"]))
    agent_service.start_round(handler.name)
    return Accepted()


@router.post("/api/rounds/{round_id}/stop", operation_id="stop_round")
def stop_round(round_id: str, handler: Senior, db: Database) -> Round:
    """Stop an open round as a senior handler; it records nothing more."""
    stop(db, round_still_open(db, round_id), handler.name)
    return one_round(db, round_id)


@router.post(
    "/api/rounds/{round_id}/proposals/{proposal_id}/decision",
    operation_id="decide_proposal",
    status_code=202,
)
def decide_proposal(
    round_id: str,
    proposal_id: int,
    request: ReviewRequest,
    handler: Senior,
    db: Database,
) -> Accepted:
    """Pass a senior handler's approval or rejection to the agent's service."""
    row = round_still_open(db, round_id)
    proposal_with_status(db, row, proposal_id, ProposalStatus.WAITING)
    agent_service.decide_proposal(
        round_id, proposal_id, request.decision, request.reason, handler.name
    )
    return Accepted()


@router.get("/api/recipes", operation_id="list_recipes")
def list_recipes(db: Database) -> list[Recipe]:
    """List the recipe's versions, newest first, each with what it changed."""
    rows = list(db.execute(select(recipes).order_by(recipes.c.version)).mappings())
    before = [None, *(row["recipe"] for row in rows)]
    listed = [
        Recipe(**row, diff=[] if old is None else diff(old, row["recipe"]))
        for old, row in zip(before, rows, strict=False)
    ]
    return listed[::-1]


# The agent's service's operations


@router.post("/api/runs/rounds", operation_id="create_round")
def create_round(request: CreateRoundRequest, db: Database) -> RoundDetails:
    """Record a new round on the current version and recipe, with the settings."""
    if (row := find_open_round(db)) is not None:
        raise HTTPException(409, OPEN_ROUND.format(number=row["number"]))
    round_id = str(uuid.uuid4())
    db.execute(
        insert(rounds).values(
            round_id=round_id,
            thread_id=str(uuid.uuid4()),
            stage=RoundStage.FIRST_EVALUATIONS,
            recipe_version=newest_recipe(db),
            settings=current_settings(db).model_dump(),
            models_allowed=[model.model_dump() for model in models_allowed(db)],
            version_before=current_version(db).version,
            started_by=request.started_by,
            started_at=now(),
        )
    )
    return round_details(db, round_id)


@router.get(
    "/api/runs/rounds/{round_id}/instructions",
    operation_id="get_improver_instructions",
)
def get_improver_instructions(round_id: str, db: Database) -> ImproverInstructions:
    """Get the improver's instructions, wrapping the recipe the round follows."""
    row = round_row(db, round_id)
    wrapper = (INSTRUCTIONS / "improver.md").read_text(encoding="utf-8")
    recipe = recipe_text(db, row["recipe_version"])
    return ImproverInstructions(instructions=wrapper.replace("{recipe}", recipe))


@router.get("/api/runs/rounds/{round_id}/results", operation_id="read_results")
def read_results(round_id: str, db: Database) -> ImproverResults:
    """Get what the improver reads; from the held-out set, the scores alone."""
    return improver_view.results(db, round_row(db, round_id))


@router.post("/api/runs/rounds/{round_id}/improving", operation_id="start_improving")
def start_improving(round_id: str, db: Database) -> Round:
    """Hand a round to the improver, once the current version has its scores."""
    row = round_still_open(db, round_id)
    require_stage(row, "hand over to the improver", RoundStage.FIRST_EVALUATIONS)
    if missing := evaluations_missing(db, row["version_before"], FINISHED):
        raise HTTPException(
            409,
            f"Version {row['version_before']} still needs "
            f"{len(missing)} of its first evaluations",
        )
    scores = version_scores(db, row["version_before"], expected_answers(db))
    held_out = scores.held_out.model_dump() if scores.held_out else None
    set_round(db, round_id, stage=RoundStage.IMPROVING, scores_before=held_out)
    return one_round(db, round_id)


@router.post(
    "/api/runs/rounds/{round_id}/proposals/changes",
    operation_id="record_change_proposal",
)
def record_change_proposal(
    round_id: str, request: ChangeProposalRequest, db: Database
) -> Proposal:
    """Record the improver's proposed change, waiting for a handler."""
    row = round_still_open(db, round_id)
    require_stage(row, "take a change", RoundStage.IMPROVING)
    if row["version_tried"] is not None:
        raise HTTPException(409, f"Round {row['number']} has already tried a version")
    check_allowed(row, request.model, request.reasoning_effort)
    return add_proposal(
        db,
        row,
        ProposalKind.CHANGE,
        based_on=row["version_before"],
        **request.model_dump(),
    )


@router.post(
    "/api/runs/rounds/{round_id}/proposals/recipes",
    operation_id="record_recipe_proposal",
)
def record_recipe_proposal(
    round_id: str, request: RecipeProposalRequest, db: Database
) -> Proposal:
    """Record the improver's proposed recipe, waiting for a handler."""
    row = round_still_open(db, round_id)
    require_stage(row, "take a recipe", RoundStage.IMPROVING, RoundStage.VERDICT)
    return add_proposal(
        db,
        row,
        ProposalKind.RECIPE,
        based_on=newest_recipe(db),
        **request.model_dump(),
    )


@router.post(
    "/api/runs/rounds/{round_id}/proposals/{proposal_id}/review",
    operation_id="record_proposal_decision",
)
def record_proposal_decision(
    round_id: str, proposal_id: int, request: RecordReviewRequest, db: Database
) -> Proposal:
    """Record a handler's decision on a proposal, before the improver resumes."""
    row = round_still_open(db, round_id)
    require_stage(row, "take a decision", *WAITING)
    proposal_with_status(db, row, proposal_id, ProposalStatus.WAITING)
    approved = request.decision == Review.APPROVE
    db.execute(
        update(proposals)
        .where(proposals.c.proposal_id == proposal_id)
        .values(
            status=ProposalStatus.APPROVED if approved else ProposalStatus.REJECTED,
            decided_by=request.handler,
            decided_at=now(),
            rejection=None if approved else request.reason,
        )
    )
    back = RoundStage.VERDICT if row["verdict"] else RoundStage.IMPROVING
    set_round(db, round_id, stage=back)
    [decided] = [p for p in proposals_of(db, round_id) if p.proposal_id == proposal_id]
    return decided


@router.post("/api/runs/rounds/{round_id}/versions", operation_id="create_version")
def create_version(
    round_id: str, request: FromProposalRequest, db: Database
) -> AgentVersion:
    """Record the approved change as a new version, untried until its verdict."""
    row = round_still_open(db, round_id)
    require_stage(row, "make a version", RoundStage.IMPROVING)
    if row["version_tried"] is not None:
        raise HTTPException(409, f"Round {row['number']} has already tried a version")
    proposal = proposal_with_status(
        db, row, request.proposal_id, ProposalStatus.APPROVED
    )
    before = find_version(db, row["version_before"])
    version = db.execute(select(func.max(agent_versions.c.version))).scalar_one() + 1
    db.execute(
        insert(agent_versions).values(
            version=version,
            instructions=proposal["instructions"],
            model=proposal["model"],
            reasoning_effort=proposal["reasoning_effort"],
            based_on=before.version,
            change=describe_change(before, proposal),
            reason=proposal["reason"],
            proposed_by=PROPOSED_BY.format(number=row["number"]),
            approved_by=proposal["decided_by"],
            approved_at=proposal["decided_at"],
            round_id=round_id,
            proposal_id=proposal["proposal_id"],
            verdict=None,
            created_at=now(),
        )
    )
    set_round(db, round_id, version_tried=version, reason=proposal["reason"])
    return find_version(db, version)


@router.post("/api/runs/rounds/{round_id}/recipes", operation_id="create_recipe")
def create_recipe(round_id: str, request: FromProposalRequest, db: Database) -> Recipe:
    """Record the approved recipe as the newest, for the rounds that follow."""
    row = round_still_open(db, round_id)
    require_stage(row, "make a recipe", RoundStage.IMPROVING, RoundStage.VERDICT)
    proposal = proposal_with_status(
        db, row, request.proposal_id, ProposalStatus.APPROVED
    )
    made = select(recipes).where(recipes.c.proposal_id == proposal["proposal_id"])
    if db.execute(made).first() is not None:
        raise HTTPException(409, f"Proposal {request.proposal_id} is already a recipe")
    newest = newest_recipe(db)
    query = (
        insert(recipes)
        .values(
            version=newest + 1,
            recipe=proposal["recipe"],
            reason=proposal["reason"],
            proposed_by=PROPOSED_BY.format(number=row["number"]),
            approved_by=proposal["decided_by"],
            approved_at=proposal["decided_at"],
            round_id=round_id,
            proposal_id=proposal["proposal_id"],
            created_at=now(),
        )
        .returning(recipes)
    )
    recipe = db.execute(query).mappings().one()
    return Recipe(**recipe, diff=diff(recipe_text(db, newest), recipe["recipe"]))


@router.post(
    "/api/runs/rounds/{round_id}/evaluations", operation_id="create_round_evaluation"
)
def create_round_evaluation(
    round_id: str, request: RoundEvaluationRequest, db: Database
) -> Run:
    """Record a round's evaluation of a version, if it can likely afford it."""
    row = round_still_open(db, round_id)
    check_evaluation_needed(db, row, request)
    check_affordable(db, row, request)
    fields = request.model_dump() | {
        "agents": round_settings(row).agents,
        "tiny": False,
        "round_id": round_id,
    }
    run = new_evaluation(db, fields)
    if request.version == row["version_tried"]:
        set_round(db, round_id, stage=RoundStage.EVALUATIONS)
    return find_run(db, run["run_id"])


@router.post("/api/runs/rounds/{round_id}/verdict", operation_id="record_verdict")
def record_verdict(round_id: str, db: Database) -> Round:
    """Keep the version a round tried, or roll it back, by UnderCover's rule."""
    row = round_still_open(db, round_id)
    require_stage(row, "take its verdict", RoundStage.IMPROVING, RoundStage.EVALUATIONS)
    if row["version_tried"] is None or row["verdict"] is not None:
        raise HTTPException(409, f"Round {row['number']} has no version to judge")
    tried = evaluations_of(db, row["version_tried"])
    if any(run["status"] == RunStatus.RUNNING for run in tried):
        raise HTTPException(409, f"Round {row['number']}'s evaluation is running")
    after = version_scores(db, row["version_tried"], expected_answers(db)).held_out
    decided = decide(db, row, after)
    outcome = VersionVerdict.KEPT if decided.kept else VersionVerdict.ROLLED_BACK
    set_verdict(db, row["version_tried"], outcome)
    set_round(
        db,
        round_id,
        stage=RoundStage.VERDICT,
        verdict=outcome,
        why=decided.why,
        scores_after=after.model_dump() if after else None,
    )
    return one_round(db, round_id)


@router.post(
    "/api/runs/rounds/{round_id}/model-calls", operation_id="record_round_model_call"
)
def record_round_model_call(
    round_id: str, request: RoundModelCallRequest, db: Database
) -> Round:
    """Record the tokens and cost of one of the improver's model calls."""
    round_still_open(db, round_id)
    db.execute(
        insert(round_model_calls).values(
            round_id=round_id, **request.model_dump(), created_at=now()
        )
    )
    return one_round(db, round_id)


@router.post("/api/runs/rounds/{round_id}/finish", operation_id="finish_round")
def finish_round(round_id: str, db: Database) -> Round:
    """Finish an open round once the improver ends its work."""
    row = round_still_open(db, round_id)
    require_stage(row, "finish", *WORKING)
    first = row["stage"] == RoundStage.FIRST_EVALUATIONS
    why = {"why": "its first evaluations didn't all finish"} if first else {}
    close(db, row, RoundStage.FINISHED, **why)
    return one_round(db, round_id)


@router.post("/api/runs/rounds/stop", operation_id="stop_working_rounds")
def stop_working_rounds(db: Database) -> list[str]:
    """Stop the rounds the service was working, keeping those waiting for a handler."""
    query = select(rounds).where(rounds.c.stage.in_(WORKING))
    stopped = list(db.execute(query).mappings())
    for row in stopped:
        stop(db, row, RESTART)
    return [row["round_id"] for row in stopped]
