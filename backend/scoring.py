"""The lab's measures of the agent's work against the handlers' decisions: whether an
answer is right, what a mistake costs, and an evaluation's measures."""

from typing import NamedTuple

from backend.models import DecisionKind, Measures, ScoredClaim, Scores

WRONGFUL_DECLINE = 1500
NEEDLESS_REFERRAL = 50
# A payout within a dollar of the handler's is right.
PAYOUT_TOLERANCE = 1


class Answer(NamedTuple):
    """A decision on a claim and its payout, the agent's or a handler's."""

    decision: DecisionKind
    payout: float


def answer_of(decision: DecisionKind | None, payout: float | None) -> Answer:
    """Return the agent's answer on a claim, with a claim it didn't decide counted
    as a referral."""
    if decision is None:
        return Answer(DecisionKind.REFER, 0)
    return Answer(decision, payout or 0)


def is_right(answer: Answer, expected: Answer) -> bool:
    """Say whether the decision matches the handler's and the payout is within a
    dollar."""
    return (
        answer.decision == expected.decision
        and abs(answer.payout - expected.payout) <= PAYOUT_TOLERANCE
    )


def mistake_cost(answer: Answer, expected: Answer) -> float:
    """Return what the agent's answer costs UnderCover against the handler's: a
    wrongful decline, a wrongful approval's payout whether or not it was paid, a
    needless referral, or the difference on a right approval."""
    if answer.decision == expected.decision:
        if answer.decision == DecisionKind.APPROVE:
            return abs(answer.payout - expected.payout)
        return 0
    if answer.decision == DecisionKind.DECLINE:
        return WRONGFUL_DECLINE
    if answer.decision == DecisionKind.APPROVE:
        return answer.payout
    return NEEDLESS_REFERRAL


def average_grade(claims: list[ScoredClaim]) -> float | None:
    """The judge's average score on the claims it graded, or none if it graded
    none."""
    graded = [claim.grade.score for claim in claims if claim.grade is not None]
    return sum(graded) / len(graded) if graded else None


def measures(
    claims: list[ScoredClaim],
    model_cost: float,
    run_seconds: float | None,
    judge_cost: float,
) -> Measures:
    """Score an evaluation from its claims, its model cost, its time and what the
    judge cost."""
    count = len(claims)
    agreed = [
        answer_of(c.decision, c.payout).decision == c.handler_decision for c in claims
    ]
    referred = [
        answer_of(c.decision, c.payout).decision == DecisionKind.REFER for c in claims
    ]
    return Measures(
        decision_accuracy=sum(agreed) / count,
        accuracy=sum(c.right for c in claims) / count,
        cost_of_mistakes=sum(c.mistake_cost for c in claims),
        straight_through=sum(not r for r in referred) / count,
        model_cost_per_claim=model_cost / count,
        seconds_per_claim=sum(c.seconds for c in claims) / count,
        run_seconds=run_seconds,
        grade=average_grade(claims),
        judge_cost=judge_cost,
    )


def average(runs: list[Measures]) -> Scores | None:
    """Average the measures of several evaluations of one set, or nothing with no
    evaluations. A run with no grade leaves the average with none, so a version is
    never kept on the grades of some of its runs."""
    if not runs:
        return None
    count = len(runs)
    fields = [name for name in Scores.model_fields if name not in ("runs", "grade")]
    grades = [run.grade for run in runs]
    return Scores(
        runs=count,
        grade=None
        if None in grades
        else sum(g for g in grades if g is not None) / count,
        **{name: sum(getattr(run, name) for run in runs) / count for name in fields},
    )
