"""Rounds and their evaluations, which the backend's tests play out as the agent's
service would."""

import json

from sqlalchemy import update

from backend.database import DATA, engine, runs
from backend.tests.claim_requests import decide, record_call, start
from backend.tests.run_requests import create_evaluation, finish

# The held-out set's five tiny claims, oldest submitted first.
TINY_HELD_OUT = ["CLM-1114", "CLM-1106", "CLM-1112", "CLM-1104", "CLM-1110"]
HANDLERS = {
    "evaluation": "evals/decisions.json",
    "held_out": "evals/held_out_decisions.json",
}
MODEL = {"model": "openai/gpt-6-luna", "reasoning_effort": "low"}


def handlers_answers(evaluation_set):
    """The handler's decision and payout on each claim of a set, by claim."""
    path = DATA / HANDLERS[evaluation_set]
    labels = json.loads(path.read_text(encoding="utf-8"))
    return {label["claim_id"]: (label["decision"], label["payout"]) for label in labels}


def round_path(round_id, *parts):
    return "/".join(["/api/runs/rounds", round_id, *parts])


def create_round(client, started_by="Dana Whitfield"):
    return client.post("/api/runs/rounds", json={"started_by": started_by})


def open_round(client):
    """The round that's open, or a new one."""
    listed = client.get("/api/rounds").json()
    live = [r for r in listed if r["stage"] not in ("finished", "stopped")]
    return live[0] if live else create_round(client).json()


def round_evaluation(client, round_id, evaluation_set, version=1, **model):
    return client.post(
        round_path(round_id, "evaluations"),
        json={"evaluation_set": evaluation_set, "version": version, **MODEL, **model},
    )


def work_copies(client, run, evaluation_set, right, cost=0.0):
    """Decide each of an evaluation's copies the way the handler decided it, or
    refer every one, with a model call costing what's given, and finish it."""
    answers = handlers_answers(evaluation_set)
    for copy in run["claims"]:
        start(client, copy["claim_id"])
        if cost:
            record_call(client, copy["claim_id"], run["run_id"], cost=cost)
        original = copy["claim_id"].rsplit("-E", 1)[0]
        decision, payout = answers[original] if right else ("refer", 0)
        decide(client, copy["claim_id"], decision, payout)
    finish(client, run["run_id"])


def play_evaluation(client, evaluation_set, right, in_round=True, tiny=False):
    """Work an evaluation, in the open round or none, and return its id. A tiny one
    is put in the round by hand, since a round runs whole sets."""
    if in_round and not tiny:
        round_id = open_round(client)["round_id"]
        run = round_evaluation(client, round_id, evaluation_set).json()
    else:
        run = create_evaluation(client, evaluation_set, tiny=tiny).json()
        if in_round:
            with engine().begin() as db:
                db.execute(
                    update(runs)
                    .where(runs.c.run_id == run["run_id"])
                    .values(round_id=open_round(client)["round_id"])
                )
    work_copies(client, run, evaluation_set, right)
    return run["run_id"]


def play_round_evaluation(client, round_id, evaluation_set, right, version=1):
    """Work one of a round's evaluations of a version, and return its id."""
    run = round_evaluation(client, round_id, evaluation_set, version).json()
    work_copies(client, run, evaluation_set, right)
    return run["run_id"]


def first_evaluations(client, round_id, right=False, cost=0.0):
    """Work the current version's first evaluations in a round: one of the
    evaluation set and two of the held-out set."""
    for evaluation_set in ("evaluation", "held_out", "held_out"):
        run = round_evaluation(client, round_id, evaluation_set).json()
        work_copies(client, run, evaluation_set, right, cost)


def propose_change(client, round_id, **changes):
    body = {
        "instructions": "# UnderCover Agent\n\nRefer a claim missing a document.",
        "model": "openai/gpt-6-luna",
        "reasoning_effort": "low",
        "reason": "Fewer wrongful approvals",
    } | changes
    return client.post(round_path(round_id, "proposals", "changes"), json=body)


def propose_recipe(client, round_id, recipe="1. Read the results.\n2. Improve."):
    body = {"recipe": recipe, "reason": "Rules for kinds of mistakes"}
    return client.post(round_path(round_id, "proposals", "recipes"), json=body)


def review(client, round_id, proposal_id, decision="approve", reason=""):
    body = {"decision": decision, "reason": reason, "handler": "Dana Whitfield"}
    return client.post(
        round_path(round_id, "proposals", str(proposal_id), "review"), json=body
    )


def tried_version(client, round_id, right):
    """Have a round's approved change become a version and evaluate it, and return
    the round with its verdict."""
    proposal = propose_change(client, round_id).json()
    review(client, round_id, proposal["proposal_id"])
    version = client.post(
        round_path(round_id, "versions"),
        json={"proposal_id": proposal["proposal_id"]},
    ).json()["version"]
    for evaluation_set in ("evaluation", "held_out", "held_out"):
        play_round_evaluation(client, round_id, evaluation_set, right, version)
    return client.post(round_path(round_id, "verdict")).json()
