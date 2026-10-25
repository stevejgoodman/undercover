import pytest
from sqlalchemy import insert

from backend.database import agent_versions, engine
from backend.tests.rounds_played import play_evaluation
from backend.tests.run_requests import create_dispatch, create_evaluation, finish

SECOND = {
    "version": 2,
    "instructions": "# UnderCover Agent\n\nDecide the claim.\nCheck the manual.",
    "model": "openai/gpt-6-luna",
    "reasoning_effort": "medium",
    "based_on": 1,
    "change": "Instructions and reasoning effort",
    "reason": "Fewer wrongful approvals",
    "proposed_by": "The improver, round 1",
    "approved_by": "Dana Whitfield",
    "approved_at": "2026-10-24T10:00:00+00:00",
    "round_id": None,
    "verdict": None,
    "created_at": "2026-10-24T10:00:00+00:00",
}


def add_version(**fields):
    with engine().begin() as db:
        db.execute(insert(agent_versions).values(SECOND | fields))


def test_version_1_is_the_claim_agent_as_it_was(client):
    current = client.get("/api/configuration/current").json()
    assert (current["version"], current["model"]) == (1, "openai/gpt-6-luna")
    assert (current["reasoning_effort"], current["verdict"]) == ("low", "kept")
    assert current["instructions"].startswith("# UnderCover Agent: working a claim")
    assert (current["proposed_by"], current["approved_by"]) == (
        "UnderCover",
        "UnderCover",
    )
    assert "scores" not in current


def test_the_claim_agents_version_holds_no_scores(client):
    agent = client.get("/api/configuration/versions/1/agent").json()
    assert set(agent) == {"version", "instructions", "model", "reasoning_effort"}
    assert client.get("/api/configuration/versions/9/agent").status_code == 404


def test_a_dispatch_and_an_evaluation_record_their_version(client):
    add_version(verdict="kept")
    dispatch = create_dispatch(client).json()
    evaluation = create_evaluation(client).json()
    assert (dispatch["version"], evaluation["version"]) == (1, 1)
    with_two = client.post(
        "/api/runs/dispatches",
        json={"agents": 3, "version": 2, "model": "m", "reasoning_effort": "low"},
    )
    assert with_two.json()["version"] == 2
    unknown = client.post(
        "/api/runs/dispatches",
        json={"agents": 3, "version": 9, "model": "m", "reasoning_effort": "low"},
    )
    assert unknown.status_code == 404
    assert client.get("/api/dispatches/latest").json()["version"] == 2


def test_the_current_version_is_the_newest_kept(client):
    add_version()
    assert client.get("/api/configuration/current").json()["version"] == 1
    add_version(version=3, verdict="rolled_back")
    assert client.get("/api/configuration/current").json()["version"] == 1
    add_version(version=4, verdict="kept")
    assert client.get("/api/configuration/current").json()["version"] == 4
    listed = client.get("/api/configuration/versions").json()
    assert [(v["version"], v["current"]) for v in listed] == [
        (4, True),
        (3, False),
        (2, False),
        (1, False),
    ]


def test_a_versions_scores_count_only_the_whole_set_evaluations_rounds_ran(client):
    first = play_evaluation(client, "held_out", right=True)
    second = play_evaluation(client, "held_out", right=False)
    measures = [
        client.get(f"/api/evaluations/{run_id}").json()["measures"]
        for run_id in (first, second)
    ]
    held_out = client.get("/api/configuration/versions/1").json()["scores"]["held_out"]
    assert held_out["runs"] == 2
    for name in (
        "decision_accuracy",
        "accuracy",
        "cost_of_mistakes",
        "straight_through",
    ):
        assert held_out[name] == pytest.approx(
            (measures[0][name] + measures[1][name]) / 2
        )

    play_evaluation(client, "held_out", right=True, in_round=False)
    play_evaluation(client, "held_out", right=True, tiny=True)
    stopped = create_evaluation(client, "held_out", tiny=False).json()["run_id"]
    client.post("/api/runs/stop")
    running = create_evaluation(client, "held_out", tiny=False).json()["run_id"]
    assert running != stopped

    again = client.get("/api/configuration/versions/1").json()["scores"]
    assert again["held_out"] == held_out
    assert again["evaluation"] is None
    finish(client, running)


def test_a_version_shows_what_it_changed(client):
    add_version(instructions="Decide the claim.\nCheck the manual.")
    add_version(
        version=3, based_on=2, instructions="Decide the claim.\nCheck the wording."
    )
    third = client.get("/api/configuration/versions/3").json()
    assert third["diff"] == [
        {"change": "unchanged", "text": "Decide the claim."},
        {"change": "removed", "text": "Check the manual."},
        {"change": "added", "text": "Check the wording."},
    ]
    assert third["scores"] == {"evaluation": None, "held_out": None}
    assert client.get("/api/configuration/versions/1").json()["diff"] == []
    assert client.get("/api/configuration/versions/9").status_code == 404


def test_a_version_shows_what_it_changed_from_the_one_it_was_based_on(client):
    add_version(
        instructions="Decide the claim.\nAsk for receipts.", verdict="rolled_back"
    )
    add_version(version=3, based_on=1, instructions="Decide the claim.")
    lines = client.get("/api/configuration/versions/3").json()["diff"]
    assert {line["text"] for line in lines} >= {"Decide the claim."}
    assert "Ask for receipts." not in {line["text"] for line in lines}
    assert any(line["change"] == "removed" for line in lines)


def test_the_instructions_operation_is_gone(client):
    assert client.get("/api/instructions").status_code == 404
