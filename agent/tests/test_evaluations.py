"""Evaluations: the agent's service works copies of a labeled set's claims, and the
backend scores them."""

import threading
from functools import partial

import pytest
from langchain_core.exceptions import ModelRateLimitError
from langgraph.checkpoint.memory import InMemorySaver

from agent import api, dispatcher, harness, tools
from agent.tests.dispatching import dispatch
from agent.tests.queue_setup import leave_waiting
from agent.tests.records import claim_of, evaluations, model_calls_of, work_times_of
from agent.tests.stubs import decide, graph_on, setup, stub, swarm
from backend.tests.run_requests import latest_dispatch, queue

TINY = ["CLM-1007", "CLM-1015", "CLM-1017", "CLM-1020", "CLM-1021"]


def test_an_evaluation_through_the_service(client, serve):
    before = queue(client)
    outage = RuntimeError("503: The model is unavailable")
    model = swarm(
        {
            "CLM-1007-E1": decide("approve", 50.0),
            "CLM-1015-E1": decide("approve", 300.0),
            "CLM-1017-E1": decide("decline", 0),
            "CLM-1020-E1": decide("approve", 1240.0),
            "CLM-1021-E1": [outage, outage],
        }
    )
    saver = InMemorySaver()
    response = serve(model, saver).post(
        "/api/evaluations",
        json={"evaluation_set": "evaluation", "tiny": True, "agents": 5},
    )
    assert response.status_code == 202

    [listed] = evaluations(client)
    assert (listed["status"], listed["agents"], listed["size"]) == ("finished", 5, 5)
    assert queue(client) == before
    held = claim_of(client, "CLM-1020-E1")
    assert held["status"] == "waiting_for_sign_off"
    assert saver.get_tuple(harness.thread_of(held)) is None
    paid = claim_of(client, "CLM-1007-E1")
    assert saver.get_tuple(harness.thread_of(paid)) is not None
    assert claim_of(client, "CLM-1021-E1")["status"] == "left_for_handler"

    evaluation = client.get(f"/api/evaluations/{listed['run_id']}").json()
    measures = evaluation["measures"]
    assert (measures["decision_accuracy"], measures["accuracy"]) == (0.4, 0.2)
    assert measures["cost_of_mistakes"] == 2850.0
    assert measures["straight_through"] == 0.8
    copies = [f"{claim_id}-E1" for claim_id in TINY]
    cost = sum(c["cost"] for i in copies for c in model_calls_of(i))
    seconds = sum(w["seconds"] for i in copies for w in work_times_of(i))
    assert measures["model_cost_per_claim"] == pytest.approx(cost / 5)
    assert measures["seconds_per_claim"] == pytest.approx(seconds / 5)
    assert cost == pytest.approx(0.0042 * 8)


def test_a_dispatch_leaves_an_evaluations_copies_alone(client):
    leave_waiting("CLM-1001")
    api.create_evaluation("held_out", True, setup(5))
    client.post("/api/claims/CLM-1104-E1/start", json={"thread_id": "copy-thread"})
    dispatch(swarm({"CLM-1001": decide("refer", 0)}))

    assert [c["claim_id"] for c in latest_dispatch(client)["claims"]] == ["CLM-1001"]
    copy = claim_of(client, "CLM-1104-E1")
    assert (copy["status"], copy["thread_id"]) == ("in_progress", "copy-thread")
    assert claim_of(client, "CLM-1106-E1")["status"] == "waiting"


@pytest.mark.parametrize(
    "starts",
    [
        ("/api/dispatches", "/api/evaluations", "Dispatch #1 is running"),
        ("/api/evaluations", "/api/dispatches", "Evaluation #1 is running"),
    ],
)
def test_a_dispatch_and_an_evaluation_never_run_together(
    client, serve, held_run, starts
):
    first, second, running = starts
    leave_waiting()
    agent = serve(stub())
    body = {"evaluation_set": "held_out", "tiny": True, "agents": 3}
    working = threading.Thread(target=agent.post, args=(first,), kwargs={"json": body})
    working.start()
    assert held_run.working.wait(5)

    refused = agent.post(second, json=body)
    assert refused.status_code == 409
    assert refused.json()["detail"] == running
    held_run.release.set()
    working.join(5)
    assert not working.is_alive()


def test_the_agent_cant_read_the_scoreboard():
    for name in (
        "list_evaluations",
        "get_evaluation",
        "start_dispatch",
        "start_evaluation",
        "list_versions",
        "get_version",
        "read_results",
        "get_round",
        "create_round",
        "record_verdict",
    ):
        assert not hasattr(api, name)
    claim_agents_modules = [harness, tools, dispatcher]
    for module in claim_agents_modules:
        assert not hasattr(module, "improver_api")


def test_a_copy_still_failing_after_its_tries_is_left_in_progress(client):
    run = api.create_evaluation("held_out", True, setup(5))
    limited = ModelRateLimitError("429 Too Many Requests")
    scripts = {copy["claim_id"]: decide("refer", 0) for copy in run["claims"]}
    model = swarm(scripts | {"CLM-1104-E1": [limited] * 3})
    work = partial(
        harness.work_in_run, new_graph=partial(graph_on, model, InMemorySaver())
    )
    reports = dispatcher.work_run(run, work, set())

    assert (
        "CLM-1104-E1  left in progress: ModelRateLimitError: 429 Too Many Requests"
        in reports
    )
    assert claim_of(client, "CLM-1104-E1")["status"] == "in_progress"
