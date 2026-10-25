import json

import httpx
import pytest

from backend import spending
from backend.database import DATA, ROOT, engine, seed
from backend.models import AllowedModel
from backend.tests.claim_requests import start
from backend.tests.judging import COST
from backend.tests.rounds_played import (
    create_round,
    first_evaluations,
    play_round_evaluation,
    propose_change,
    propose_recipe,
    review,
    round_evaluation,
    round_path,
    tried_version,
    work_copies,
)
from backend.tests.run_requests import finish
from backend.tests.settings_requests import FIRST
from backend.tests.signing import MARCUS

LUNA, GEMINI = "openai/gpt-6-luna", "google/gemini-3.5-flash-lite"
RESTART = {"stopped_by": "A restart"}


@pytest.fixture
def round_id(client):
    return create_round(client).json()["round_id"]


def current(client):
    return client.get("/api/configuration/current").json()["version"]


def round_of(client, round_id):
    return client.get(f"/api/rounds/{round_id}").json()


def lab_recipe():
    lab = json.loads((ROOT / "labs/week2day5.ipynb").read_text(encoding="utf-8"))
    for cell in lab["cells"]:
        source = "".join(cell["source"])
        if source.startswith('RECIPE = """'):
            return source.split('"""')[1]
    raise AssertionError("The lab has no recipe")


def test_the_first_recipe_is_the_labs(client):
    [first] = client.get("/api/recipes").json()
    assert first["version"] == 1
    assert first["recipe"] == lab_recipe()
    assert first["diff"] == []


def test_a_round_starts_on_the_current_version_and_recipe(client, round_id):
    details = round_of(client, round_id)
    assert (details["stage"], details["version_before"]) == ("first_evaluations", 1)
    assert (details["recipe_version"], details["started_by"]) == (1, "Dana Whitfield")
    assert details["first_evaluations_missing"] == [
        "evaluation",
        "held_out",
        "held_out",
    ]
    assert details["progress"] == {"done": 0, "of": 3}
    assert details["settings"]["spending_limit"] == 0.5
    assert [m["model"] for m in details["models_allowed"]][0] == "openai/gpt-6-luna"
    assert create_round(client).status_code == 409


def test_the_improvers_instructions_wrap_the_recipe(client, round_id):
    path = round_path(round_id, "instructions")
    instructions = client.get(path).json()["instructions"]
    assert instructions.startswith("# The improver")
    assert instructions.rstrip().endswith(lab_recipe().rstrip())
    assert "{recipe}" not in instructions


def test_the_first_evaluations_count_toward_the_versions_scores(client, round_id):
    play_round_evaluation(client, round_id, "evaluation", right=False)
    assert round_of(client, round_id)["progress"] == {"done": 1, "of": 3}
    early = client.post(round_path(round_id, "improving"))
    assert early.status_code == 409
    for _ in range(2):
        play_round_evaluation(client, round_id, "held_out", right=False)
    improving = client.post(round_path(round_id, "improving")).json()
    assert improving["stage"] == "improving"
    assert improving["scores_before"]["runs"] == 2
    held_out = client.get("/api/configuration/versions/1").json()["scores"]["held_out"]
    assert improving["scores_before"] == held_out


def test_the_improvers_view_holds_nothing_from_the_held_out_set_but_its_scores(
    client, round_id
):
    first_evaluations(client, round_id, right=False)
    client.post(round_path(round_id, "improving"))
    results = client.get(round_path(round_id, "results")).json()
    assert results["current_version"]["version"] == 1
    assert results["current_version"]["instructions"].startswith("# UnderCover Agent")
    assert (
        "## Contents of the claims manual"
        not in results["current_version"]["instructions"]
    )
    assert results["scores"]["held_out"]["runs"] == 2
    assert results["scores"]["evaluation"]["runs"] == 1
    assert results["wrong"]
    wrong = results["wrong"][0]
    assert set(wrong) == {"claim_id", "summary", "agent", "handler", "judge"}
    assert set(wrong["handler"]) == {"decision", "payout", "reason", "reference"}
    assert wrong["agent"]["decision"] == "refer"
    assert wrong["judge"]["letter"] == "B"
    assert len(results["explained_least_well"]) == 5
    assert results["objectives_on_the_held_out_set"] == FIRST["objectives"]
    assert results["rule"].startswith("A new version is kept when")
    assert results["spending_left"] == pytest.approx(0.5 - 75 * COST)
    assert [m["model"] for m in results["models_allowed"]][0] == "openai/gpt-6-luna"

    text = json.dumps(results)
    held_out = json.loads(
        (DATA / "evals/held_out_decisions.json").read_text(encoding="utf-8")
    )
    for label in held_out:
        assert label["claim_id"] not in text
        assert label["reason"] not in text
    evaluation = json.loads((DATA / "evals/decisions.json").read_text(encoding="utf-8"))
    assert any(label["reason"] in text for label in evaluation)


def test_a_round_keeps_its_settings_when_they_change(client, round_id):
    raised = FIRST | {
        "objectives": {"accuracy": 0.99, "grade": 2.9},
        "spending_limit": 5.0,
    }
    assert client.put("/api/settings", json=raised).status_code == 200
    first_evaluations(client, round_id, right=False)
    client.post(round_path(round_id, "improving"))
    results = client.get(round_path(round_id, "results")).json()
    assert results["objectives_on_the_held_out_set"] == FIRST["objectives"]
    assert round_of(client, round_id)["spending_limit"] == 0.5
    decided = tried_version(client, round_id, right=True)
    assert decided["verdict"] == "kept"


def test_a_version_kept_by_the_rule_becomes_current(client, round_id):
    first_evaluations(client, round_id, right=False)
    client.post(round_path(round_id, "improving"))
    decided = tried_version(client, round_id, right=True)
    assert (decided["stage"], decided["verdict"]) == ("verdict", "kept")
    assert "accuracy" in decided["why"]
    assert decided["scores_after"]["accuracy"] == 1.0
    assert decided["scores_after"]["accuracy"] > decided["scores_before"]["accuracy"]
    assert current(client) == 2
    version = client.get("/api/configuration/versions/2").json()
    assert (version["based_on"], version["approved_by"]) == (1, "Dana Whitfield")
    assert version["change"] == "Instructions"
    assert version["proposed_by"] == "The improver, round 1"


def test_a_version_that_improves_nothing_is_rolled_back(client, round_id):
    first_evaluations(client, round_id, right=True)
    client.post(round_path(round_id, "improving"))
    decided = tried_version(client, round_id, right=True)
    assert decided["verdict"] == "rolled_back"
    assert decided["why"] == "no measure improved by more than the noise"
    assert current(client) == 1
    assert client.get("/api/configuration/versions/2").json()["verdict"] == (
        "rolled_back"
    )


def test_a_proposal_changes_nothing_until_approved(client, round_id):
    first_evaluations(client, round_id)
    client.post(round_path(round_id, "improving"))
    proposal = propose_change(client, round_id, reasoning_effort="medium").json()
    assert proposal["status"] == "waiting"
    assert (proposal["model_before"], proposal["reasoning_effort_before"]) == (
        "openai/gpt-6-luna",
        "low",
    )
    assert any(line["change"] == "added" for line in proposal["diff"])
    assert round_of(client, round_id)["stage"] == "waiting_for_change"
    assert len(client.get("/api/configuration/versions").json()) == 1
    making = {"proposal_id": proposal["proposal_id"]}
    assert client.post(round_path(round_id, "versions"), json=making).status_code == 409
    rejected = review(client, round_id, proposal["proposal_id"], "reject", "Too vague")
    assert (rejected.json()["status"], rejected.json()["rejection"]) == (
        "rejected",
        "Too vague",
    )
    assert client.post(round_path(round_id, "versions"), json=making).status_code == 409
    assert len(client.get("/api/configuration/versions").json()) == 1
    assert round_of(client, round_id)["stage"] == "improving"


def test_a_proposal_outside_the_models_allowed_is_refused(client, round_id):
    first_evaluations(client, round_id)
    client.post(round_path(round_id, "improving"))
    refused = propose_change(
        client, round_id, model="openai/gpt-7", reasoning_effort="low"
    )
    assert refused.status_code == 422
    effort = propose_change(client, round_id, reasoning_effort="none")
    assert effort.status_code == 422
    assert round_of(client, round_id)["proposals"] == []


def test_a_recipe_approved_becomes_the_newest(client, round_id):
    first_evaluations(client, round_id)
    client.post(round_path(round_id, "improving"))
    tried_version(client, round_id, right=True)
    proposal = propose_recipe(client, round_id).json()
    assert round_of(client, round_id)["stage"] == "waiting_for_recipe"
    assert proposal["based_on"] == 1
    review(client, round_id, proposal["proposal_id"])
    made = client.post(
        round_path(round_id, "recipes"), json={"proposal_id": proposal["proposal_id"]}
    ).json()
    assert (made["version"], made["approved_by"]) == (2, "Dana Whitfield")
    assert any(line["change"] == "removed" for line in made["diff"])
    finished = client.post(round_path(round_id, "finish")).json()
    assert finished["stage"] == "finished"
    second = create_round(client).json()
    assert second["recipe_version"] == 2
    assert second["version_before"] == 2


def test_an_evaluation_over_the_limit_is_refused(client, round_id):
    # 25 claims at a cent each, and the judge's calls, is about $0.2505.
    run = round_evaluation(client, round_id, "evaluation").json()
    work_copies(client, run, "evaluation", right=False, cost=0.01)
    refused = round_evaluation(client, round_id, "held_out")
    assert refused.status_code == 402
    assert refused.json()["detail"] == (
        "The evaluation could cost about $0.25, and $0.25 of the round's limit is left"
    )
    raised = FIRST | {"spending_limit": 1.0}
    client.put("/api/settings", json=raised)
    assert round_evaluation(client, round_id, "held_out").status_code == 402


def test_a_model_with_no_runs_is_estimated_from_its_prices(client, round_id):
    run = round_evaluation(client, round_id, "evaluation").json()
    work_copies(client, run, "evaluation", right=False, cost=0.002)
    models = [AllowedModel(**m) for m in round_of(client, round_id)["models_allowed"]]
    per_claim = 0.002 + COST
    with engine().connect() as db:
        luna = spending.estimate(db, 25, LUNA, LUNA, models)
        gemini = spending.estimate(db, 25, GEMINI, LUNA, models)
        unknown = spending.estimate(db, 25, GEMINI, "nobody/nothing", models)
    assert luna == pytest.approx(25 * per_claim)
    # The larger of 0.3 / 0.1 for input and 2.5 / 0.5 for output.
    assert gemini == pytest.approx(25 * per_claim * 5)
    assert unknown == 0


def test_an_evaluation_cut_short_by_the_limit_shows_as_stopped(client, round_id):
    run = round_evaluation(client, round_id, "evaluation").json()
    copies = [copy["claim_id"] for copy in run["claims"]]
    start(client, copies[0])
    client.post(
        round_path(round_id, "model-calls"),
        json={"input_tokens": 1, "output_tokens": 1, "cost": 0.5},
    )
    refused = start(client, copies[1])
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Round 1 has spent its limit"
    finished = finish(client, run["run_id"]).json()
    assert finished["status"] == "stopped"


def test_a_version_whose_evaluations_were_stopped_is_rolled_back(client, round_id):
    first_evaluations(client, round_id, right=False)
    client.post(round_path(round_id, "improving"))
    proposal = propose_change(client, round_id).json()
    review(client, round_id, proposal["proposal_id"])
    client.post(
        round_path(round_id, "versions"), json={"proposal_id": proposal["proposal_id"]}
    )
    run = round_evaluation(client, round_id, "evaluation", 2).json()
    assert round_of(client, round_id)["stage"] == "evaluations"
    assert round_of(client, round_id)["progress"] == {"done": 1, "of": 3}
    client.post("/api/runs/stop")
    finish(client, run["run_id"])
    decided = client.post(round_path(round_id, "verdict")).json()
    assert (decided["verdict"], decided["why"]) == (
        "rolled_back",
        "its evaluations were stopped",
    )


def test_a_version_the_round_cant_afford_to_evaluate_is_rolled_back(client, round_id):
    first_evaluations(client, round_id, right=False)
    client.post(round_path(round_id, "improving"))
    proposal = propose_change(client, round_id).json()
    review(client, round_id, proposal["proposal_id"])
    client.post(
        round_path(round_id, "versions"), json={"proposal_id": proposal["proposal_id"]}
    )
    decided = client.post(round_path(round_id, "verdict")).json()
    assert decided["why"] == "the round couldn't afford to evaluate it"
    assert current(client) == 1


def test_a_round_stopped_before_its_verdict_leaves_the_current_version(
    client, round_id
):
    first_evaluations(client, round_id, right=False)
    client.post(round_path(round_id, "improving"))
    proposal = propose_change(client, round_id).json()
    review(client, round_id, proposal["proposal_id"])
    client.post(
        round_path(round_id, "versions"), json={"proposal_id": proposal["proposal_id"]}
    )
    run = round_evaluation(client, round_id, "evaluation", 2).json()
    stopped = client.post(f"/api/rounds/{round_id}/stop").json()
    assert (stopped["stage"], stopped["stopped_by"]) == ("stopped", "Dana Whitfield")
    assert stopped["verdict"] == "rolled_back"
    assert current(client) == 1
    assert client.get(f"/api/evaluations/{run['run_id']}").json()["status"] == (
        "stopped"
    )
    for path, body in [
        (round_path(round_id, "verdict"), None),
        (
            round_path(round_id, "model-calls"),
            {"input_tokens": 1, "output_tokens": 1, "cost": 0},
        ),
        (round_path(round_id, "finish"), None),
    ]:
        refused = client.post(path, json=body)
        assert refused.status_code == 409
        assert refused.json()["detail"] == "Round 1 is stopped"
    assert start(client, run["claims"][0]["claim_id"]).status_code == 409


def test_a_round_stopped_after_its_verdict_keeps_it(client, round_id):
    first_evaluations(client, round_id, right=False)
    client.post(round_path(round_id, "improving"))
    tried_version(client, round_id, right=True)
    stopped = client.post(f"/api/rounds/{round_id}/stop").json()
    assert stopped["verdict"] == "kept"
    assert current(client) == 2


def test_only_a_senior_handler_stops_a_round(client, client_as, anonymous, round_id):
    refused = client_as(MARCUS).post(f"/api/rounds/{round_id}/stop")
    assert refused.status_code == 403
    assert anonymous.post(f"/api/rounds/{round_id}/stop").status_code == 401
    assert round_of(client, round_id)["stage"] == "first_evaluations"


def test_a_senior_handler_starts_a_round_through_the_service(
    client, client_as, agent_calls
):
    assert client.post("/api/rounds").status_code == 202
    assert agent_calls == [("/api/rounds", {"handler": "Dana Whitfield"})]
    assert client_as(MARCUS).post("/api/rounds").status_code == 403
    create_round(client)
    refused = client.post("/api/rounds")
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "Round 1 is open, and only one round is open at a time"
    )
    assert len(agent_calls) == 1


def test_a_decision_on_a_proposal_goes_to_the_service(
    client, client_as, agent_calls, agent_answers, round_id
):
    first_evaluations(client, round_id)
    client.post(round_path(round_id, "improving"))
    proposal = propose_change(client, round_id).json()
    path = f"/api/rounds/{round_id}/proposals/{proposal['proposal_id']}/decision"
    rejection = {"decision": "reject", "reason": "Name no claims"}
    assert client.post(path, json=rejection).status_code == 202
    assert agent_calls == [
        (
            f"/api/rounds/{round_id}/proposals/{proposal['proposal_id']}/decision",
            {
                "decision": "reject",
                "reason": "Name no claims",
                "handler": "Dana Whitfield",
            },
        )
    ]
    assert round_of(client, round_id)["proposals"][0]["status"] == "waiting"
    assert (
        client.post(path, json={"decision": "reject", "reason": " "}).status_code == 422
    )
    assert client_as(MARCUS).post(path, json=rejection).status_code == 403
    assert len(agent_calls) == 1

    agent_answers(
        lambda request: httpx.Response(409, json={"detail": "Dispatch #4 is running"})
    )
    busy = client.post(path, json={"decision": "approve", "reason": ""})
    assert (busy.status_code, busy.json()["detail"]) == (409, "Dispatch #4 is running")

    review(client, round_id, proposal["proposal_id"])
    assert client.post(path, json=rejection).status_code == 409


def test_a_restart_stops_working_rounds_and_keeps_waiting_ones(client, round_id):
    first_evaluations(client, round_id)
    client.post(round_path(round_id, "improving"))
    propose_change(client, round_id)
    assert client.post("/api/runs/rounds/stop", json=RESTART).json() == []
    assert round_of(client, round_id)["stage"] == "waiting_for_change"
    client.post(f"/api/rounds/{round_id}/stop")
    working = create_round(client).json()["round_id"]
    assert client.post("/api/runs/rounds/stop", json=RESTART).json() == [working]
    assert round_of(client, working)["stopped_by"] == "A restart"


def test_a_rounds_cost_is_the_improver_its_evaluations_and_the_judge(client, round_id):
    run = round_evaluation(client, round_id, "evaluation").json()
    work_copies(client, run, "evaluation", right=False, cost=0.001)
    client.post(
        round_path(round_id, "model-calls"),
        json={"input_tokens": 3000, "output_tokens": 400, "cost": 0.004},
    )
    assert round_of(client, round_id)["cost"] == pytest.approx(
        25 * 0.001 + 25 * COST + 0.004
    )
    listed = client.get("/api/rounds").json()
    assert [r["round_id"] for r in listed] == [round_id]


def test_a_round_finished_before_its_first_evaluations_says_why(client, round_id):
    finished = client.post(round_path(round_id, "finish")).json()
    assert (finished["stage"], finished["version_tried"]) == ("finished", None)
    assert finished["why"] == "its first evaluations didn't all finish"


def test_a_version_below_the_objectives_is_rolled_back(client, round_id):
    first_evaluations(client, round_id, right=False)
    client.post(round_path(round_id, "improving"))
    decided = tried_version(client, round_id, right=False)
    assert decided["why"] == "it missed the objectives on accuracy"
    assert current(client) == 1


def improving(client, round_id, right=False):
    first_evaluations(client, round_id, right=right)
    client.post(round_path(round_id, "improving"))


def version_made(client, round_id):
    proposal = propose_change(client, round_id).json()
    review(client, round_id, proposal["proposal_id"])
    made = client.post(
        round_path(round_id, "versions"), json={"proposal_id": proposal["proposal_id"]}
    )
    return proposal, made


def test_a_verdict_is_recorded_once_and_extra_evaluations_are_refused(client, round_id):
    improving(client, round_id, right=True)
    decided = tried_version(client, round_id, right=True)
    assert decided["verdict"] == "rolled_back"
    extra = round_evaluation(client, round_id, "held_out", 2)
    assert extra.status_code == 409
    again = client.post(round_path(round_id, "verdict"))
    assert again.status_code == 409
    assert current(client) == 1


def test_a_version_gets_each_of_its_evaluations_once(client, round_id):
    improving(client, round_id)
    version_made(client, round_id)
    play_round_evaluation(client, round_id, "evaluation", right=True, version=2)
    assert round_evaluation(client, round_id, "evaluation", 2).status_code == 409
    assert round_evaluation(client, round_id, "held_out", 1).status_code == 409


def test_the_first_evaluations_are_taken_only_while_missing(client, round_id):
    play_round_evaluation(client, round_id, "evaluation", right=False)
    refused = round_evaluation(client, round_id, "evaluation")
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "Round 1 doesn't need an evaluation of the evaluation set on version 1"
    )


def test_a_verdict_waits_for_the_evaluation_running(client, round_id):
    improving(client, round_id)
    version_made(client, round_id)
    round_evaluation(client, round_id, "evaluation", 2)
    refused = client.post(round_path(round_id, "verdict"))
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Round 1's evaluation is running"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("proposals/changes", None),
        ("proposals/recipes", {"recipe": "1. Read.", "reason": "Shorter"}),
        ("versions", {"proposal_id": 1}),
        ("verdict", None),
    ],
)
def test_the_improvers_writes_wait_for_the_improving_stage(
    client, round_id, path, body
):
    if body is None and path == "proposals/changes":
        refused = propose_change(client, round_id)
    else:
        refused = client.post(round_path(round_id, *path.split("/")), json=body)
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith(
        "Round 1 is at the first evaluations stage, so it can't"
    )


def test_a_change_after_a_version_was_tried_is_refused(client, round_id):
    improving(client, round_id)
    version_made(client, round_id)
    refused = propose_change(client, round_id)
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Round 1 has already tried a version"


def test_an_approved_proposal_makes_one_version_or_recipe(client, round_id):
    improving(client, round_id)
    proposal, made = version_made(client, round_id)
    assert made.status_code == 200
    again = client.post(
        round_path(round_id, "versions"), json={"proposal_id": proposal["proposal_id"]}
    )
    assert again.status_code == 409
    recipe = propose_recipe(client, round_id).json()
    review(client, round_id, recipe["proposal_id"])
    body = {"proposal_id": recipe["proposal_id"]}
    assert client.post(round_path(round_id, "recipes"), json=body).status_code == 200
    assert client.post(round_path(round_id, "recipes"), json=body).status_code == 409
    assert len(client.get("/api/recipes").json()) == 2


def test_a_round_finished_before_its_verdict_rolls_its_version_back(client, round_id):
    improving(client, round_id)
    version_made(client, round_id)
    finished = client.post(round_path(round_id, "finish")).json()
    assert (finished["verdict"], finished["why"]) == (
        "rolled_back",
        "the round ended before its verdict",
    )
    version = client.get("/api/configuration/versions/2").json()
    assert version["verdict"] == "rolled_back"
    assert current(client) == 1


def test_a_proposal_waiting_when_the_round_stops_is_rejected(client, round_id):
    improving(client, round_id)
    propose_change(client, round_id)
    client.post(f"/api/rounds/{round_id}/stop")
    [proposal] = round_of(client, round_id)["proposals"]
    assert (proposal["status"], proposal["rejection"]) == (
        "rejected",
        "The round was stopped",
    )


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("improving", None),
        ("proposals/recipes", {"recipe": "1. Read.", "reason": "Shorter"}),
        ("proposals/1/review", {"decision": "approve", "reason": "", "handler": "D"}),
        ("versions", {"proposal_id": 1}),
        ("recipes", {"proposal_id": 1}),
        ("evaluations", None),
        ("verdict", None),
        ("model-calls", {"input_tokens": 1, "output_tokens": 1, "cost": 0}),
        ("finish", None),
    ],
)
def test_a_stopped_round_records_nothing_more(client, round_id, path, body):
    client.post(f"/api/rounds/{round_id}/stop")
    if path == "evaluations":
        refused = round_evaluation(client, round_id, "evaluation")
    else:
        refused = client.post(round_path(round_id, *path.split("/")), json=body)
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Round 1 is stopped"


def test_a_version_cut_short_by_the_limit_is_rolled_back(client, round_id):
    improving(client, round_id)
    version_made(client, round_id)
    run = round_evaluation(client, round_id, "evaluation", 2).json()
    start(client, run["claims"][0]["claim_id"])
    client.post(
        round_path(round_id, "model-calls"),
        json={"input_tokens": 1, "output_tokens": 1, "cost": 0.5},
    )
    assert finish(client, run["run_id"]).json()["status"] == "stopped"
    decided = client.post(round_path(round_id, "verdict")).json()
    assert (decided["verdict"], decided["why"]) == (
        "rolled_back",
        "its evaluations were stopped",
    )
    assert current(client) == 1


def test_seeding_empties_the_rounds(client, round_id):
    seed(engine())
    assert client.get("/api/rounds").json() == []
    assert len(client.get("/api/recipes").json()) == 1
