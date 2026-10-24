"""The agent's service's rounds of improvement: starting one, passing on a
handler's decision, and one dispatch, evaluation or stretch of a round's work at a
time."""

import threading
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent import improver, improver_api, service
from agent.tests.dispatching import new_dispatch
from agent.tests.improving import improvement, reads_and_proposes, script
from agent.tests.queue_setup import leave_waiting
from agent.tests.stubs import call, stub
from backend.tests.settings_requests import FIRST


@pytest.fixture(autouse=True)
def plenty_to_spend(client):
    client.put("/api/settings", json=FIRST | {"spending_limit": 10.0})


@pytest.fixture
def rounds_served(serve):
    """The service, with rounds on stub models whose improver keeps its progress
    in memory across stretches."""
    work = improvement(InMemorySaver())
    service.app.dependency_overrides[service.build_improvement] = lambda: work
    return serve(stub())


def the_round(client):
    [round] = client.get("/api/rounds").json()
    return improver_api.get_round(round["round_id"])


def decision_path(round):
    [proposal] = [p for p in round["proposals"] if p["status"] == "waiting"]
    return (
        f"/api/rounds/{round['round_id']}/proposals/{proposal['proposal_id']}/decision"
    )


def test_a_round_started_on_the_service_waits_for_a_handler(
    client, rounds_served, monkeypatch
):
    script(monkeypatch, *reads_and_proposes())
    started = rounds_served.post("/api/rounds", json={"handler": "Dana Whitfield"})
    assert started.status_code == 202
    round = the_round(client)
    assert (round["stage"], round["started_by"]) == (
        "waiting_for_change",
        "Dana Whitfield",
    )
    assert service.one_thing.what == ""


def test_a_decision_is_recorded_with_its_handler_before_the_improver_resumes(
    client, rounds_served, monkeypatch
):
    seen = []
    carry_on = improver.carry_on_round

    def resume_after_looking(round_id, proposal, decision, work):
        seen.append(improver_api.get_round(round_id)["proposals"][0])
        carry_on(round_id, proposal, decision, work)

    monkeypatch.setattr(service, "carry_on_round", resume_after_looking)
    script(
        monkeypatch,
        *reads_and_proposes(),
        call(
            "propose_change",
            **{
                "instructions": "Refer a claim missing a receipt.",
                "model": "openai/gpt-6-luna",
                "reasoning_effort": "low",
                "reason": "Second try",
            },
        ),
    )
    rounds_served.post("/api/rounds", json={"handler": "Dana Whitfield"})
    body = {
        "decision": "reject",
        "reason": "Name no claims",
        "handler": "Dana Whitfield",
    }
    decided = rounds_served.post(decision_path(the_round(client)), json=body)
    assert decided.status_code == 202
    [before_resuming] = seen
    assert (before_resuming["status"], before_resuming["decided_by"]) == (
        "rejected",
        "Dana Whitfield",
    )
    assert the_round(client)["stage"] == "waiting_for_change"


def test_a_decision_while_a_dispatch_runs_is_refused_with_nothing_recorded(
    client, rounds_served, held_run, monkeypatch
):
    script(monkeypatch, *reads_and_proposes())
    rounds_served.post("/api/rounds", json={"handler": "Dana Whitfield"})
    round = the_round(client)
    leave_waiting()
    dispatching = threading.Thread(
        target=rounds_served.post,
        args=("/api/dispatches",),
        kwargs={"json": {"agents": 3}},
    )
    dispatching.start()
    assert held_run.working.wait(5)

    body = {"decision": "approve", "reason": "", "handler": "Dana Whitfield"}
    refused = rounds_served.post(decision_path(round), json=body)
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Dispatch #4 is running"
    assert the_round(client)["proposals"][0]["status"] == "waiting"

    held_run.release.set()
    dispatching.join(5)
    assert not dispatching.is_alive()


def test_a_dispatch_and_an_evaluation_run_while_a_round_waits(
    client, rounds_served, monkeypatch
):
    script(monkeypatch, *reads_and_proposes())
    rounds_served.post("/api/rounds", json={"handler": "Dana Whitfield"})
    leave_waiting()
    assert rounds_served.post("/api/dispatches", json={"agents": 3}).status_code == 202
    evaluation = {"evaluation_set": "held_out", "tiny": True, "agents": 5}
    assert rounds_served.post("/api/evaluations", json=evaluation).status_code == 202
    assert the_round(client)["stage"] == "waiting_for_change"


def test_a_rounds_work_holds_the_one_thing_at_a_time(
    client, rounds_served, monkeypatch
):
    working, release = threading.Event(), threading.Event()

    def held(round, work):
        working.set()
        release.wait(5)

    monkeypatch.setattr(service, "work_round", held)
    starting = threading.Thread(
        target=rounds_served.post,
        args=("/api/rounds",),
        kwargs={"json": {"handler": "Dana Whitfield"}},
    )
    starting.start()
    assert working.wait(5)
    refused = rounds_served.post("/api/dispatches", json={"agents": 3})
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 is running",
    )
    release.set()
    starting.join(5)
    assert rounds_served.post("/api/dispatches", json={"agents": 3}).status_code == 202


def test_a_round_whose_work_fails_is_stopped(client, rounds_served, monkeypatch):
    script(monkeypatch, RuntimeError("The model broke"))
    rounds_served.post("/api/rounds", json={"handler": "Dana Whitfield"})
    round = the_round(client)
    assert round["stage"] == "stopped"
    assert (
        round["stopped_by"] == "An error in the improver: RuntimeError: The model broke"
    )
    assert not service.one_thing.lock.locked()


def test_starting_the_service_stops_working_rounds(client, monkeypatch):
    improver_api.create_round("Dana Whitfield")
    new_dispatch()
    monkeypatch.setattr(service, "checkpoint_pool", lambda: nullcontext(None))
    with TestClient(service.app):
        pass
    assert the_round(client)["stage"] == "stopped"
    assert the_round(client)["stopped_by"] == "A restart"
