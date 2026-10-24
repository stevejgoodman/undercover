import threading
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent import harness, service
from agent.tests.dispatching import new_dispatch
from agent.tests.queue_setup import leave_waiting
from agent.tests.records import claim_of, steps_of
from agent.tests.stubs import decide, graph_on, stub, swarm
from api_rules import rule_breaks
from backend.tests.run_requests import latest_dispatch


def resume(agent, claim_id):
    return agent.post(f"/api/claims/{claim_id}/resume")


def start_dispatch(agent, agents):
    return agent.post("/api/dispatches", json={"agents": agents})


def test_the_service_follows_the_api_rules():
    assert rule_breaks(service.app.openapi()) == []


def test_health():
    assert TestClient(service.app).get("/api/health").json() == {"status": "ok"}


def test_a_sign_off_picks_the_claim_up_and_pays_it_once(
    client, serve, agent_calls, traces
):
    model, saver = stub(*decide("approve", 1350.0)), InMemorySaver()
    harness.work_claim("CLM-1002", None, graph_on(model, saver))
    signed = client.post("/api/claims/CLM-1002/sign-off")
    assert agent_calls == [("/api/claims/CLM-1002/resume", None)]

    agent = serve(model, saver)
    response = resume(agent, "CLM-1002")
    assert response.status_code == 202
    claim = claim_of(client, "CLM-1002")
    assert claim["status"] == "decided"
    assert claim["payment"]["amount"] == 1350.0
    assert claim["payment"]["signed_off_by"] == "Dana Whitfield"
    signed_off_at = signed.json()["decision"]["signed_off_at"]
    assert claim["payment"]["signed_off_at"] == signed_off_at
    assert len(model.prompts) == 2
    session = f"CLM-1002:{claim['thread_id']}"
    assert [(t["langfuse_session_id"], t["langfuse_trace_name"]) for t in traces] == [
        (session, "Work claim"),
        (session, "Carry on"),
    ]

    assert resume(agent, "CLM-1002").status_code == 409
    assert claim_of(client, "CLM-1002")["payment"] == claim["payment"]


def test_a_claim_is_kept_from_dispatches_while_it_is_resumed(
    client, serve, monkeypatch
):
    model, saver = stub(*decide("approve", 1350.0)), InMemorySaver()
    harness.work_claim("CLM-1002", None, graph_on(model, saver))
    client.post("/api/claims/CLM-1002/sign-off")
    seen = []
    carry_on = service.carry_on

    def watch(claim_id, run_id, graph):
        seen.append(set(service.resuming))
        return carry_on(claim_id, run_id, graph)

    monkeypatch.setattr(service, "carry_on", watch)
    assert resume(serve(model, saver), "CLM-1002").status_code == 202
    assert seen == [{"CLM-1002"}]
    assert service.resuming == set()


def test_a_claim_waiting_for_sign_off_is_not_picked_up(client, serve):
    model, saver = stub(*decide("approve", 1350.0)), InMemorySaver()
    harness.work_claim("CLM-1002", None, graph_on(model, saver))
    before = steps_of(client, "CLM-1002")
    response = resume(serve(model, saver), "CLM-1002")
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Claim CLM-1002 has no sign-off waiting to be paid"
    )
    assert claim_of(client, "CLM-1002")["status"] == "waiting_for_sign_off"
    assert steps_of(client, "CLM-1002") == before


def test_a_claim_in_progress_without_a_sign_off_is_left_to_its_agent(client, serve):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "working"})
    response = resume(serve(stub()), "CLM-1001")
    assert response.status_code == 409
    claim = claim_of(client, "CLM-1001")
    assert (claim["status"], claim["attempts"]) == ("in_progress", 1)
    assert steps_of(client, "CLM-1001") == []


def test_an_unknown_claim(serve):
    response = resume(serve(stub()), "CLM-9999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Claim CLM-9999 not found"


def test_start_a_dispatch(client, serve):
    ids = ["CLM-1001", "CLM-1003", "CLM-1004"]
    leave_waiting(*ids)
    scripts = {claim_id: decide("refer", 0) for claim_id in ids}
    model = swarm(scripts, pause=0.05, fill=2)
    response = start_dispatch(serve(model), 2)
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}

    dispatch = latest_dispatch(client)
    assert (dispatch["status"], dispatch["agents"]) == ("finished", 2)
    assert (dispatch["model"], dispatch["reasoning_effort"]) == ("stub", "none")
    assert [c["status"] for c in dispatch["claims"]] == ["decided"] * 3
    assert model.most_at_once == 2


@pytest.mark.parametrize("agents", [0, 26])
def test_a_dispatch_has_1_to_25_claim_agents(client, serve, agents):
    assert start_dispatch(serve(stub()), agents).status_code == 422
    assert latest_dispatch(client) is None


def test_one_run_at_a_time(client, serve, held_run):
    leave_waiting()
    agent = serve(stub())
    first = threading.Thread(target=start_dispatch, args=(agent, 3))
    first.start()
    assert held_run.working.wait(5)
    [resuming] = held_run.resuming
    assert resuming is service.resuming

    refused = start_dispatch(agent, 3)
    assert refused.status_code == 409
    assert refused.json()["detail"] == "A dispatch or an evaluation is already running"
    assert latest_dispatch(client)["number"] == 1

    held_run.release.set()
    first.join(5)
    assert not first.is_alive()
    assert latest_dispatch(client)["status"] == "finished"
    assert start_dispatch(agent, 3).status_code == 202
    assert latest_dispatch(client)["number"] == 2


def test_a_dispatch_whose_dispatcher_fails_is_stopped(client, serve, monkeypatch):
    leave_waiting()
    work_run = service.work_run

    def broken(run, work, resuming):
        raise RuntimeError("The backend is unreachable")

    monkeypatch.setattr(service, "work_run", broken)
    agent = serve(stub())
    assert start_dispatch(agent, 3).status_code == 202
    assert latest_dispatch(client)["status"] == "stopped"

    monkeypatch.setattr(service, "work_run", work_run)
    assert start_dispatch(agent, 3).status_code == 202
    assert latest_dispatch(client)["status"] == "finished"


def test_starting_the_service_stops_the_runs_left_running(client, monkeypatch):
    run_id = new_dispatch()["run_id"]
    monkeypatch.setattr(service, "checkpoint_pool", lambda: nullcontext(object()))
    with TestClient(service.app):
        dispatch = latest_dispatch(client)
        assert (dispatch["run_id"], dispatch["status"]) == (run_id, "stopped")
