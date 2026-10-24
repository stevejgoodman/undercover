"""Evaluations the backend's tests play out as a round's would be, until rounds
can record their own."""

import json

from sqlalchemy import update

from backend.database import DATA, engine, runs
from backend.tests.claim_requests import decide, start
from backend.tests.run_requests import create_evaluation, finish

# The held-out set's five tiny claims, oldest submitted first.
TINY_HELD_OUT = ["CLM-1114", "CLM-1106", "CLM-1112", "CLM-1104", "CLM-1110"]
HANDLERS = {
    "evaluation": "evals/decisions.json",
    "held_out": "evals/held_out_decisions.json",
}


def handlers_answers(evaluation_set):
    """The handlers' decision and payout on each claim of a set, by claim."""
    path = DATA / HANDLERS[evaluation_set]
    labels = json.loads(path.read_text(encoding="utf-8"))
    return {label["claim_id"]: (label["decision"], label["payout"]) for label in labels}


def play_evaluation(
    client, evaluation_set, right, round_id: str | None = "round-1", tiny=False
):
    """Work an evaluation's copies, every one the way the handler decided it, or
    every one referred, and finish it, in a round, or none."""
    run = create_evaluation(client, evaluation_set, tiny=tiny).json()
    with engine().begin() as db:
        db.execute(
            update(runs).where(runs.c.run_id == run["run_id"]).values(round_id=round_id)
        )
    answers = handlers_answers(evaluation_set)
    for copy in run["claims"]:
        start(client, copy["claim_id"])
        original = copy["claim_id"].rsplit("-E", 1)[0]
        decision, payout = answers[original] if right else ("refer", 0)
        decide(client, copy["claim_id"], decision, payout)
    finish(client, run["run_id"])
    return run["run_id"]
