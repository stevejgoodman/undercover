"""Jev, the judge, as in the lab: it grades the agent's reason for each claim of an
evaluation against the handler's reason and reference, through OpenRouter's
Decisions endpoint. The endpoint is in alpha, so the call is written once, here.
It runs in the backend, which holds the handlers' reasons.

Each call times out after 10 seconds for each phase of the request, and the whole
batch after GRADING_DEADLINE, so finishing an evaluation stays well inside the 30
seconds the agent's service waits for it."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, wait
from typing import NamedTuple

import httpx
from openrouter import OpenRouter
from openrouter.components import (
    DecisionsNoulAnswer,
    DecisionsResponse,
    DecisionsScoreAnswer,
    QuestionsTypedDict,
)
from openrouter.errors import OpenRouterError

from backend.lookups import free_model
from backend.models import Letter

JEV = "typesafe/jev-1.13"
# The client ignores an address set on it, so each call passes this origin.
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai")
TIMEOUT_MS = 10_000
GRADING_DEADLINE = 15
JUDGES_AT_ONCE = 25

# Jev numbers the grades by their position in the list, so F is 0 and A is 3.
RUBRIC: dict[Letter, str] = {
    "F": "different grounds from the handler's reason, or it contradicts the "
    "handler's reason",
    "C": "partly the same as the handler's reason: one of the handler's grounds or "
    "the section is missing, or it adds a ground the handler did not give",
    "B": "the same grounds and the same section of the policy wording as the "
    "handler's reason",
    "A": "the same grounds and section as the handler's reason, and clearly better "
    "expressed: clearer for the customer, with the section and the figures, "
    "shorter, and no jargon",
}
GRADES: list[Letter] = list(RUBRIC)
QUESTIONS: dict[str, QuestionsTypedDict] = {
    "grade": {
        "type": "score",
        "instructions": "An expert claims handler decided a travel insurance claim "
        "and gave `handler.reason`, resting on `handler.reference`. Grade how well "
        "`agent.reason`, resting on `agent.section`, explains the same decision.",
        "criteria": [f"{letter}: {text}" for letter, text in RUBRIC.items()],
    },
    "same_grounds": {
        "type": "noul",
        "instructions": "`agent.reason` gives the same main grounds for the "
        "decision as `handler.reason`",
    },
    "same_section": {
        "type": "noul",
        "instructions": "`agent.section` or `agent.reason` refers to the same "
        "section of the policy wording as `handler.reference`",
    },
}

log = logging.getLogger(__name__)
jev = OpenRouter(api_key=lambda: os.getenv("OPENROUTER_API_KEY"), client=httpx.Client())


class HandlersAnswer(NamedTuple):
    decision: str
    reason: str
    reference: str


class AgentsAnswer(NamedTuple):
    decision: str
    reason: str
    section: str


class ToGrade(NamedTuple):
    """One claim of an evaluation: the handler's answer, and the agent's, or none
    if it didn't decide."""

    claim_id: str
    handler: HandlersAnswer
    agent: AgentsAnswer | None


class Graded(NamedTuple):
    """Jev's score from 0 to 3, the most likely grade as its letter, the two checks
    as probabilities, and what the call cost in US dollars."""

    score: float
    letter: Letter
    same_grounds: float
    same_section: float
    cost: float


UNDECIDED = Graded(score=0, letter=GRADES[0], same_grounds=0, same_section=0, cost=0)


def graded_from(response: DecisionsResponse) -> Graded | None:
    """Read Jev's answers, or nothing when they aren't the kinds asked for."""
    answers = response.answers
    grade, grounds, section = (
        answers.get(name) for name in ("grade", "same_grounds", "same_section")
    )
    if not (
        isinstance(grade, DecisionsScoreAnswer)
        and grade.probabilities
        and isinstance(grounds, DecisionsNoulAnswer)
        and isinstance(section, DecisionsNoulAnswer)
    ):
        return None
    most_likely = max(grade.probabilities, key=grade.probabilities.__getitem__)
    if response.usage.cost is None:
        log.warning("The judge didn't say what a grade cost")
    return Graded(
        score=grade.score,
        letter=GRADES[int(most_likely)],
        same_grounds=grounds.noul,
        same_section=section.noul,
        cost=response.usage.cost or 0,
    )


def ask(claim: ToGrade) -> Graded | None:
    """Grade one claim, an undecided one F without asking, or give nothing when the
    judge can't grade it."""
    if claim.agent is None:
        return UNDECIDED
    try:
        response = jev.alpha.decisions.create(
            model=JEV,
            state={"handler": claim.handler._asdict(), "agent": claim.agent._asdict()},
            questions=QUESTIONS,
            server_url=OPENROUTER_URL,
            timeout_ms=TIMEOUT_MS,
            retries=None,
        )
    except (OpenRouterError, httpx.HTTPError) as error:  # left out of the average
        log.warning("The judge couldn't grade %s: %s", claim.claim_id, error)
        return None
    graded = graded_from(response)
    if graded is None:
        log.warning("The judge's answer on %s wasn't a grade", claim.claim_id)
    return graded


def grade(claims: list[ToGrade]) -> dict[str, Graded | None]:
    """Grade an evaluation's claims in parallel, by claim, leaving ungraded any not
    graded by the deadline. With a free model set, the judge isn't called."""
    if free_model():
        return {claim.claim_id: None for claim in claims}
    pool = ThreadPoolExecutor(max_workers=JUDGES_AT_ONCE)
    asked = {claim.claim_id: pool.submit(ask, claim) for claim in claims}
    wait(asked.values(), timeout=GRADING_DEADLINE)
    pool.shutdown(wait=False, cancel_futures=True)
    return {
        claim_id: future.result() if future.done() else None
        for claim_id, future in asked.items()
    }
