import json
import time

import httpx
import pytest
from sqlalchemy import update

from backend import judge
from backend.database import DATA, engine, runs
from backend.tests.claim_requests import decide, record_call, start
from backend.tests.judging import COST, answer
from backend.tests.rounds_played import TINY_HELD_OUT, handlers_answers, play_evaluation
from backend.tests.run_requests import create_evaluation, finish, get_evaluation


def evaluation_with(client, decided):
    """A tiny held-out evaluation with the copies of the originals given decided as
    the handler decided them, and the rest left undecided."""
    run = create_evaluation(client).json()
    answers = handlers_answers("held_out")
    for original in TINY_HELD_OUT:
        copy = f"{original}-E{run['number']}"
        start(client, copy)
        if original in decided:
            decide(client, copy, *answers[original])
    return run["run_id"]


def graded_claims(client, run_id):
    return {c["copy_of"]: c for c in get_evaluation(client, run_id)["claims"]}


def test_finishing_an_evaluation_asks_the_judge_about_each_decided_copy(client, jev):
    run_id = evaluation_with(client, {"CLM-1104", "CLM-1106"})
    finish(client, run_id)
    assert len(jev.requests) == 2
    request = jev.requests[0]
    assert str(request.url) == f"{judge.OPENROUTER_URL}/api/alpha/decisions"
    body = json.loads(request.content)
    assert body["model"] == "typesafe/jev-1.13"
    assert set(body["questions"]) == {"grade", "same_grounds", "same_section"}
    assert body["questions"]["grade"]["type"] == "score"
    assert [c.split(":")[0] for c in body["questions"]["grade"]["criteria"]] == [
        "F",
        "C",
        "B",
        "A",
    ]
    states = {state["handler"]["reason"]: state for state in jev.states()}
    assert len(states) == 2
    for state in states.values():
        assert set(state["handler"]) == {"decision", "reason", "reference"}
        assert set(state["agent"]) == {"decision", "reason", "section"}
        assert state["agent"]["reason"] == "The delay was covered."
        assert state["agent"]["section"] == "Section 3, Trip Delay"


def test_each_call_times_out_after_ten_seconds(client, jev):
    finish(client, evaluation_with(client, {"CLM-1104"}))
    timeout = jev.requests[0].extensions["timeout"]
    assert {timeout[kind] for kind in ("connect", "read", "write", "pool")} == {10.0}


def test_the_letter_is_the_most_likely_level_never_the_score_rounded(client, jev):
    jev.reply = answer(
        score=1.6, probabilities={"0": 0.1, "1": 0.45, "2": 0.4, "3": 0.05}
    )
    run_id = evaluation_with(client, {"CLM-1104"})
    finish(client, run_id)
    grade = graded_claims(client, run_id)["CLM-1104"]["grade"]
    assert grade == {
        "score": 1.6,
        "letter": "C",
        "same_grounds": 0.9,
        "same_section": 0.7,
    }


def test_the_score_is_jevs(client, jev):
    jev.reply = answer(
        score=1.85, probabilities={"0": 0.1, "1": 0.2, "2": 0.45, "3": 0.25}
    )
    run_id = evaluation_with(client, {"CLM-1104"})
    finish(client, run_id)
    grade = graded_claims(client, run_id)["CLM-1104"]["grade"]
    assert (grade["score"], grade["letter"]) == (1.85, "B")


def test_an_undecided_copy_is_graded_f_without_asking(client, jev):
    run_id = evaluation_with(client, set())
    finish(client, run_id)
    assert jev.requests == []
    claims = graded_claims(client, run_id)
    assert {c["grade"]["letter"] for c in claims.values()} == {"F"}
    assert {c["grade"]["score"] for c in claims.values()} == {0}
    assert get_evaluation(client, run_id)["measures"]["grade"] == 0


@pytest.mark.parametrize("failure", [500, httpx.ReadTimeout("Too slow")])
def test_a_claim_the_judge_cant_grade_is_left_out_of_the_average(client, jev, failure):
    jev.reply = failure
    run_id = evaluation_with(client, {"CLM-1104", "CLM-1106"})
    response = finish(client, run_id)
    assert response.status_code == 200
    claims = graded_claims(client, run_id)
    assert claims["CLM-1104"]["grade"] is None
    assert claims["CLM-1110"]["grade"]["letter"] == "F"
    assert len(jev.requests) == 2
    assert get_evaluation(client, run_id)["measures"]["grade"] == 0


def test_an_evaluation_with_nothing_graded_has_no_grade(client, jev):
    jev.reply = 500
    run_id = play_evaluation(client, "held_out", right=True, tiny=True)
    measures = get_evaluation(client, run_id)["measures"]
    assert (measures["grade"], measures["judge_cost"]) == (None, 0)


def test_the_judges_cost_is_apart_from_the_models(client, jev):
    run_id = evaluation_with(client, set(TINY_HELD_OUT))
    record_call(client, "CLM-1104-E1", run_id, cost=0.01)
    finish(client, run_id)
    evaluation = get_evaluation(client, run_id)
    assert evaluation["measures"]["judge_cost"] == pytest.approx(5 * COST)
    assert evaluation["model_cost"] == pytest.approx(0.01)
    assert evaluation["measures"]["grade"] == 2.0


def test_the_claims_are_graded_in_parallel(client, jev):
    def slowly(request):
        time.sleep(1)
        return httpx.Response(200, json=answer())

    jev.reply = slowly
    started = time.monotonic()
    play_evaluation(client, "evaluation", right=True)
    assert time.monotonic() - started < 5


def test_on_a_free_model_the_judge_isnt_called(client, jev, monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    run_id = evaluation_with(client, set(TINY_HELD_OUT))
    finish(client, run_id)
    assert jev.requests == []
    assert {c["grade"] for c in graded_claims(client, run_id).values()} == {None}
    assert get_evaluation(client, run_id)["measures"]["grade"] is None


def test_no_read_of_the_claim_agents_holds_the_handlers_reasons(client):
    finish(client, evaluation_with(client, set(TINY_HELD_OUT)))
    labels = json.loads(
        (DATA / "evals/held_out_decisions.json").read_text(encoding="utf-8")
    )
    reads = [
        "/api/claims",
        "/api/claims/CLM-1104-E1",
        "/api/claims/CLM-1104-E1/steps",
        f"/api/policies/{client.get('/api/claims/CLM-1104-E1').json()['policy_id']}",
        "/api/configuration/current",
        "/api/configuration/versions/1/agent",
        "/api/documents/search?query=receipt",
        "/api/documents/policy_wording/sections/3",
    ]
    customer = client.get("/api/claims/CLM-1104-E1").json()["customer_id"]
    reads.append(f"/api/customers/{customer}/claims")
    for path in reads:
        response = client.get(path)
        assert response.status_code == 200, path
        for label in labels:
            assert label["reason"] not in response.text, path
            assert label["reference"] not in response.text or "wording" in path, path


@pytest.mark.parametrize(
    "malformed",
    [
        answer(probabilities={}),
        {**answer(), "answers": {"grade": {"type": "score", "score": 2.0}}},
        {**answer(), "answers": {}},
    ],
    ids=["no probabilities", "missing probabilities", "no answers"],
)
def test_an_answer_that_isnt_a_grade_leaves_the_claim_ungraded(client, jev, malformed):
    jev.reply = malformed
    run_id = evaluation_with(client, {"CLM-1104"})
    assert finish(client, run_id).status_code == 200
    assert graded_claims(client, run_id)["CLM-1104"]["grade"] is None


def test_the_judge_is_asked_with_no_transaction_open(client, jev):
    run_id = evaluation_with(client, {"CLM-1104"})

    def stop_meanwhile(request):
        with engine().begin() as db:
            db.execute(update(runs).values(status="stopped"))
        return httpx.Response(200, json=answer())

    jev.reply = stop_meanwhile
    response = finish(client, run_id)
    assert response.status_code == 200
    assert get_evaluation(client, run_id)["status"] == "stopped"
    assert graded_claims(client, run_id)["CLM-1104"]["grade"] is None


def test_a_claim_not_graded_by_the_deadline_is_left_ungraded(client, jev, monkeypatch):
    monkeypatch.setattr(judge, "GRADING_DEADLINE", 0.2)

    def slowly(request):
        time.sleep(1)
        return httpx.Response(200, json=answer())

    jev.reply = slowly
    run_id = evaluation_with(client, {"CLM-1104"})
    started = time.monotonic()
    finish(client, run_id)
    assert time.monotonic() - started < 1
    claims = graded_claims(client, run_id)
    assert claims["CLM-1104"]["grade"] is None
    assert claims["CLM-1106"]["grade"]["letter"] == "F"
