"""What the improver reads in a round: the current version and its scores, the
evaluation set's misses and weakest explanations beside the handlers' reasons,
the earlier rounds, the round's settings and what's left to spend. From the
held-out set it holds the scores alone."""

from sqlalchemy import Connection, RowMapping, select

from backend.database import claims, handler_decisions, rounds, runs
from backend.lookups import current_version, find_version, round_left, round_settings
from backend.models import (
    AgentsAnswer,
    AllowedModel,
    ClaimBeside,
    Configuration,
    EarlierRound,
    EvaluationSet,
    HandlersAnswer,
    ImproverResults,
    RoundStage,
    RunKind,
    RunStatus,
    ScoredClaim,
)
from backend.run_views import expected_answers, score, version_scores
from backend.verdict import RULE

# The right claims explained least well that the improver reads.
LEAST_WELL = 5


def latest_evaluation_set_run(db: Connection, version: int) -> RowMapping | None:
    """A version's latest finished whole-set round evaluation of the evaluation
    set, if any."""
    query = (
        select(runs)
        .where(
            runs.c.kind == RunKind.EVALUATION,
            runs.c.version == version,
            runs.c.round_id.is_not(None),
            runs.c.tiny.is_(False),
            runs.c.status == RunStatus.FINISHED,
            runs.c.evaluation_set == EvaluationSet.EVALUATION,
        )
        .order_by(runs.c.number.desc())
        .limit(1)
    )
    return db.execute(query).mappings().first()


def handlers_on_the_evaluation_set(db: Connection) -> dict[str, HandlersAnswer]:
    """The handlers' answers on the evaluation set alone, by claim."""
    query = select(handler_decisions).where(
        handler_decisions.c.evaluation_set == EvaluationSet.EVALUATION
    )
    return {
        d["claim_id"]: HandlersAnswer(
            decision=d["decision"],
            payout=d["payout"],
            reason=d["reason"],
            reference=d["reference"],
        )
        for d in db.execute(query).mappings()
    }


def summaries(db: Connection, claim_ids: list[str]) -> dict[str, str]:
    query = select(claims.c.claim_id, claims.c.record).where(
        claims.c.claim_id.in_(claim_ids)
    )
    rows = db.execute(query).mappings()
    return {row["claim_id"]: row["record"]["summary"] for row in rows}


def beside(claim: ScoredClaim, handler: HandlersAnswer, summary: str) -> ClaimBeside:
    """One claim with the agent's answer beside the handler's and the judge's
    grade, by its original's id."""
    return ClaimBeside(
        claim_id=claim.copy_of,
        summary=summary,
        agent=AgentsAnswer(
            decision=claim.decision,
            payout=claim.payout,
            reason=claim.reason,
            section=claim.section,
        ),
        handler=handler,
        judge=claim.grade,
    )


def explained_least_well(claims_scored: list[ScoredClaim]) -> list[ScoredClaim]:
    """The right claims with the lowest grades."""
    graded = [(c.grade.score, c) for c in claims_scored if c.right and c.grade]
    graded.sort(key=lambda scored: scored[0])
    return [claim for _, claim in graded[:LEAST_WELL]]


def mistakes(
    db: Connection, version: int
) -> tuple[list[ClaimBeside], list[ClaimBeside]]:
    """From a version's latest round evaluation of the evaluation set, the claims
    it got wrong and the right ones it explained least well."""
    run = latest_evaluation_set_run(db, version)
    if run is None:
        return [], []
    scored = score(db, run, expected_answers(db)).claims
    handlers = handlers_on_the_evaluation_set(db)
    shown = summaries(db, [claim.claim_id for claim in scored])

    def as_shown(claim: ScoredClaim) -> ClaimBeside:
        return beside(claim, handlers[claim.copy_of], shown[claim.claim_id])

    wrong = [as_shown(claim) for claim in scored if not claim.right]
    return wrong, [as_shown(claim) for claim in explained_least_well(scored)]


def earlier_round(db: Connection, row: RowMapping) -> EarlierRound:
    tried = (
        None if row["version_tried"] is None else find_version(db, row["version_tried"])
    )
    return EarlierRound(
        round=row["number"],
        recipe_version=row["recipe_version"],
        version=row["version_tried"],
        model=tried.model if tried else None,
        reasoning_effort=tried.reasoning_effort if tried else None,
        reason=row["reason"],
        verdict=row["verdict"],
        why=row["why"],
        held_out_before=row["scores_before"],
        held_out_after=row["scores_after"],
    )


def rounds_so_far(db: Connection, round_id: str) -> list[EarlierRound]:
    """The rounds before this one, and this one once it has its verdict, as the
    improver's recipe asks it to look at both."""
    query = (
        select(rounds)
        .where(
            (rounds.c.round_id != round_id) | (rounds.c.verdict.is_not(None)),
            rounds.c.stage != RoundStage.FIRST_EVALUATIONS,
        )
        .order_by(rounds.c.number)
    )
    return [earlier_round(db, row) for row in db.execute(query).mappings()]


def results(db: Connection, row: RowMapping) -> ImproverResults:
    """Everything the improver reads in a round."""
    settings = round_settings(row)
    current = current_version(db)
    wrong, least_well = mistakes(db, current.version)
    return ImproverResults(
        current_version=Configuration(**current.model_dump()),
        scores=version_scores(db, current.version, expected_answers(db)),
        wrong=wrong,
        explained_least_well=least_well,
        earlier_rounds=rounds_so_far(db, row["round_id"]),
        objectives_on_the_held_out_set=settings.objectives,
        noise=settings.noise,
        tolerance=settings.tolerance,
        rule=RULE,
        spending_left=round(round_left(db, row), 4),
        models_allowed=[AllowedModel(**model) for model in row["models_allowed"]],
    )
