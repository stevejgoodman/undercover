import threading

import pytest
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
)
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from agent import harness, improver, improver_api
from agent.client import Refused
from agent.tests.improving import (
    CHANGE,
    RECIPE,
    improvement,
    new_round,
    reads_and_proposes,
    script,
)
from agent.tests.stubs import call
from backend.tests.settings_requests import FIRST

APPROVE = {"decision": "approve", "reason": ""}


@pytest.fixture(autouse=True)
def plenty_to_spend(client):
    """The stub model charges $0.0042 a call, so a round's three evaluations need
    more than the lab's $0.50."""
    client.put("/api/settings", json=FIRST | {"spending_limit": 10.0})


def waiting(round_id):
    """The proposal a round is waiting on."""
    [proposal] = [
        p
        for p in improver_api.get_round(round_id)["proposals"]
        if p["status"] == "waiting"
    ]
    return proposal


def decide(round_id, decision=APPROVE, work=None):
    """Record a handler's decision, as the service does first, and resume."""
    proposal = waiting(round_id)
    improver_api.record_proposal_decision(
        round_id,
        proposal["proposal_id"],
        decision["decision"],
        decision["reason"],
        "Dana Whitfield",
    )
    improver.carry_on_round(round_id, proposal, decision, work or improvement())


def round_evaluations(client, round_id):
    return [
        e for e in client.get("/api/evaluations").json() if e["round_id"] == round_id
    ]


def test_the_improver_is_the_labs(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    model = improver.improver_model()
    assert (model.model_name, model.reasoning_effort) == ("openai/gpt-6-luna", "medium")
    assert model.request_timeout == 300
    graph = improver.improver(InMemorySaver(), "Improve the claim agent.")
    tools = graph.nodes["tools"].bound.tools_by_name  # type: ignore[attr-defined]
    assert set(tools) == {
        "read_results",
        "propose_change",
        "run_evaluation",
        "propose_recipe",
    }
    nodes = set(graph.nodes)
    for hook in (
        "ModelCallLimitMiddleware.after_model",
        "stop_with_the_round.before_model",
        "HumanInTheLoopMiddleware.after_model",
    ):
        assert hook in nodes
    assert set(improver.APPROVAL.interrupt_on) == {"propose_change", "propose_recipe"}
    limits = [
        m for m in improver.middleware() if isinstance(m, ModelCallLimitMiddleware)
    ]
    assert [m.thread_limit for m in limits] == [improver.IMPROVER_MODEL_CALLS]


def test_the_improver_makes_one_tool_call_at_a_time(client, monkeypatch):
    model = script(monkeypatch, call("read_results"), AIMessage("Nothing to change."))
    improver.work_round(new_round(), improvement())
    assert model.bound
    assert {kwargs["parallel_tool_calls"] for kwargs in model.bound} == {False}


def test_a_round_works_its_first_evaluations_and_waits_on_a_change(client, monkeypatch):
    model = script(monkeypatch, *reads_and_proposes())
    evaluate = improver.evaluate
    progress = []

    def watching(round_id, claim_agents, evaluation_set, version):
        run = evaluate(round_id, claim_agents, evaluation_set, version)
        progress.append(improver_api.get_round(round_id)["progress"])
        return run

    monkeypatch.setattr(improver, "evaluate", watching)
    round = new_round()
    assert round["progress"] == {"done": 0, "of": 3}
    improver.work_round(round, improvement())
    assert [p["done"] for p in progress] == [1, 2, 3]

    after = improver_api.get_round(round["round_id"])
    assert after["stage"] == "waiting_for_change"
    assert after["scores_before"]["runs"] == 2
    evaluations = round_evaluations(client, round["round_id"])
    assert sorted(e["evaluation_set"] for e in evaluations) == [
        "evaluation",
        "held_out",
        "held_out",
    ]
    assert {e["version"] for e in evaluations} == {1}
    assert {e["status"] for e in evaluations} == {"finished"}
    proposal = waiting(round["round_id"])
    assert proposal["instructions"] == CHANGE["instructions"]
    system = model.prompts[0][0]
    assert isinstance(system, SystemMessage)
    assert system.text.startswith("# The improver")
    assert "1. Call read_results" in system.text


def test_a_proposal_changes_nothing_until_approved(client, monkeypatch):
    script(monkeypatch, *reads_and_proposes())
    improver.work_round(new_round(), improvement())
    assert len(client.get("/api/configuration/versions").json()) == 1
    assert client.get("/api/configuration/current").json()["version"] == 1


def test_a_whole_round_tries_a_version_and_improves_its_recipe(client, monkeypatch):
    script(
        monkeypatch,
        *reads_and_proposes(),
        call("run_evaluation"),
        call("propose_recipe", **RECIPE),
        AIMessage("The round is done."),
    )
    work = improvement()
    round = new_round()
    round_id = round["round_id"]
    improver.work_round(round, work)
    decide(round_id, work=work)

    after = improver_api.get_round(round_id)
    assert after["stage"] == "waiting_for_recipe"
    assert after["version_tried"] == 2
    assert after["verdict"] == "rolled_back"
    assert after["why"] == "it missed the objectives on accuracy"
    tried = [e for e in round_evaluations(client, round_id) if e["version"] == 2]
    assert len(tried) == 3
    assert waiting(round_id)["recipe"] == RECIPE["recipe"]

    decide(round_id, work=work)
    finished = improver_api.get_round(round_id)
    assert finished["stage"] == "finished"
    assert [r["version"] for r in client.get("/api/recipes").json()] == [2, 1]
    assert finished["cost"] > 0


def test_a_rejections_reason_reaches_the_improver(client, monkeypatch):
    model = script(
        monkeypatch,
        *reads_and_proposes(),
        call("propose_change", **CHANGE | {"reason": "Without naming claims"}),
    )
    work = improvement()
    round = new_round()
    improver.work_round(round, work)
    decide(round["round_id"], {"decision": "reject", "reason": "Name no claims"}, work)

    answer = model.prompts[-1][-1]
    assert isinstance(answer, ToolMessage)
    assert "Name no claims" in answer.text
    first, second = improver_api.get_round(round["round_id"])["proposals"]
    assert (first["status"], first["rejection"]) == ("rejected", "Name no claims")
    assert (second["status"], second["reason"]) == ("waiting", "Without naming claims")


def test_a_proposal_outside_the_models_allowed_goes_back_to_the_improver(
    client, monkeypatch
):
    model = script(
        monkeypatch,
        *reads_and_proposes(model="openai/gpt-7"),
        AIMessage("There's no change worth proposing."),
    )
    round = new_round()
    improver.work_round(round, improvement())

    refused = model.prompts[-1][-1]
    assert isinstance(refused, ToolMessage)
    assert "isn't one of the models allowed" in refused.text
    after = improver_api.get_round(round["round_id"])
    assert after["proposals"] == []
    assert (after["stage"], after["version_tried"]) == ("finished", None)


def test_an_evaluation_refused_for_the_limit_rolls_the_version_back(
    client, monkeypatch
):
    model = script(
        monkeypatch,
        *reads_and_proposes(),
        call("run_evaluation"),
        AIMessage("Stopping here."),
    )
    evaluate = improver.evaluate

    def short_of_money(round_id, claim_agents, evaluation_set, version):
        if version == 2:
            raise Refused(402, "The evaluation could cost about $0.30")
        return evaluate(round_id, claim_agents, evaluation_set, version)

    monkeypatch.setattr(improver, "evaluate", short_of_money)
    work = improvement()
    round = new_round()
    improver.work_round(round, work)
    decide(round["round_id"], work=work)

    told = model.prompts[-1][-1]
    assert told.text.startswith("Refused: The evaluation could cost about $0.30. ")
    assert (
        "Rolled back version 2: the round couldn't afford to evaluate it" in told.text
    )
    assert client.get("/api/configuration/current").json()["version"] == 1


def test_a_round_that_cant_afford_its_first_evaluations_finishes(client, monkeypatch):
    client.put("/api/settings", json=FIRST | {"spending_limit": 0.05})
    model = script(monkeypatch)
    round = new_round()
    improver.work_round(round, improvement())
    after = improver_api.get_round(round["round_id"])
    assert (after["stage"], after["why"]) == (
        "finished",
        "its first evaluations didn't all finish",
    )
    assert len(round_evaluations(client, round["round_id"])) == 1
    assert model.prompts == []


def test_stopping_a_round_mid_evaluation_starts_nothing_more(client, monkeypatch):
    model = script(monkeypatch, *reads_and_proposes(), call("run_evaluation"))
    work = improvement()
    round = new_round()
    improver.work_round(round, work)
    calls_at_stop = []
    claim_agents = work.claim_agents
    # The first claim agent of the new version's evaluation stops the round, and
    # the others wait for it, so none of them starts its claim before the stop.
    stopping_once = threading.Lock()

    def stopping_on_the_first_claim(version):
        agents = claim_agents(version)
        if version == 1:
            return agents

        def new_graph():
            with stopping_once:
                if not calls_at_stop:
                    client.post(f"/api/rounds/{round['round_id']}/stop")
                    calls_at_stop.append(len(model.prompts))
            return agents.new_graph()

        return harness.ClaimAgents(version, "stub", "default", new_graph)

    stopping = improver.Improvement(work.saver, stopping_on_the_first_claim)
    with pytest.raises(improver.RoundStopped):
        decide(round["round_id"], work=stopping)

    after = improver_api.get_round(round["round_id"])
    assert (after["stage"], after["verdict"]) == ("stopped", "rolled_back")
    assert [len(model.prompts)] == calls_at_stop
    [tried] = [
        e for e in round_evaluations(client, round["round_id"]) if e["version"] == 2
    ]
    assert tried["status"] == "stopped"
    copies = client.get(f"/api/evaluations/{tried['run_id']}").json()["claims"]
    assert {c["decision"] for c in copies} == {None}
    assert client.get("/api/configuration/current").json()["version"] == 1


def test_a_second_evaluation_or_change_goes_back_to_the_improver(client, monkeypatch):
    model = script(
        monkeypatch,
        *reads_and_proposes(),
        call("run_evaluation"),
        call("run_evaluation"),
        call("propose_change", **CHANGE | {"reason": "Another go"}),
        AIMessage("Done."),
    )
    work = improvement()
    round = new_round()
    improver.work_round(round, work)
    decide(round["round_id"], work=work)
    answers = [m.text for m in model.prompts[-1] if isinstance(m, ToolMessage)]
    assert answers[-2].startswith("Version 2 already has its verdict: Rolled back")
    assert answers[-1] == "This round has already tried version 2, its one change."
    after = improver_api.get_round(round["round_id"])
    assert after["stage"] == "finished"
    assert len(after["proposals"]) == 1


def test_a_refusal_goes_back_to_the_improver_as_its_answer(client, monkeypatch):
    model = script(monkeypatch, *reads_and_proposes(), AIMessage("Done."))

    def refused(round_id, proposal_id):
        raise Refused(409, "Round 1 has already tried a version")

    monkeypatch.setattr(improver_api, "create_version", refused)
    work = improvement()
    round = new_round()
    improver.work_round(round, work)
    decide(round["round_id"], work=work)
    answer = model.prompts[-1][-1]
    assert isinstance(answer, ToolMessage)
    assert answer.text == "Refused: Round 1 has already tried a version"
    assert improver_api.get_round(round["round_id"])["stage"] == "finished"


def test_a_round_whose_improver_proposes_nothing_finishes(client, monkeypatch):
    script(monkeypatch, call("read_results"), AIMessage("Nothing worth changing."))
    round = new_round()
    improver.work_round(round, improvement())
    after = improver_api.get_round(round["round_id"])
    assert (after["stage"], after["version_tried"]) == ("finished", None)


def test_a_round_waiting_for_a_handler_resumes_on_a_new_service(client, monkeypatch):
    script(monkeypatch, *reads_and_proposes(), AIMessage("Done."))
    saver = InMemorySaver()
    round = new_round()
    improver.work_round(round, improvement(saver))
    decide(
        round["round_id"],
        {"decision": "reject", "reason": "Not now"},
        improvement(saver),
    )
    assert improver_api.get_round(round["round_id"])["stage"] == "finished"


def test_the_improvers_work_is_one_langfuse_session(client, monkeypatch, traces):
    script(monkeypatch, *reads_and_proposes(), AIMessage("Done."))
    saver = InMemorySaver()
    round = new_round()
    improver.work_round(round, improvement(saver))
    decide(
        round["round_id"], {"decision": "reject", "reason": "No"}, improvement(saver)
    )
    session = f"Round {round['number']}:{round['round_id']}"
    improvers = [r for r in traces if r.get("langfuse_session_id") == session]
    assert len(improvers) == 2
    claims = [r for r in traces if "langfuse_tags" in r]
    assert len(claims) == 75
    assert {r["langfuse_tags"][1] for r in claims} == {round["round_id"]}
    thread: RunnableConfig = {"configurable": {"thread_id": round["thread_id"]}}
    namespaces = {
        c.config.get("configurable", {}).get("checkpoint_ns")
        for c in saver.list(thread)
    }
    assert namespaces == {""}


def test_the_improvers_model_calls_are_recorded_and_capped(client, monkeypatch):
    script(monkeypatch, *[call("read_results")] * 3)
    monkeypatch.setattr(improver, "IMPROVER_MODEL_CALLS", 2)
    round = new_round()
    with pytest.raises(ModelCallLimitExceededError):
        improver.work_round(round, improvement())
    after = improver_api.get_round(round["round_id"])
    claim_costs = sum(
        e["model_cost"] + e["measures"]["judge_cost"]
        for e in round_evaluations(client, round["round_id"])
    )
    assert after["cost"] == pytest.approx(claim_costs + 2 * 0.0042)
