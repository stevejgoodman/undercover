"""The command line, and the model and the checkpoint pool it builds."""

from contextlib import nullcontext
from typing import cast

import pytest

from agent import __main__ as cli
from agent import harness, models
from agent.client import Refused
from agent.tests.stubs import stub

# Building a version's claim agents opens no connection until a graph is built.
NO_POOL = cast(harness.Pool, None)


class FakePool:
    """Stands in for psycopg's ConnectionPool, keeping how it was opened and what
    it ran."""

    opened: list["FakePool"] = []

    def __class_getitem__(cls, _):
        return cls

    def __init__(self, conninfo, **settings):
        self.conninfo, self.settings, self.statements = conninfo, settings, []
        self.opened.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def connection(self):
        return nullcontext(self)

    def execute(self, statement):
        self.statements.append(statement)


class FakeSaver:
    """Stands in for LangGraph's PostgresSaver."""

    made: list["FakeSaver"] = []

    def __init__(self, pool):
        self.pool, self.set_up = pool, False
        self.made.append(self)

    def setup(self):
        self.set_up = True


@pytest.fixture
def fakes(monkeypatch):
    """Stand in for psycopg's pool and LangGraph's saver, and keep what is made."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@pooler.example.com/db")
    monkeypatch.setattr(FakePool, "opened", [])
    monkeypatch.setattr(FakeSaver, "made", [])
    monkeypatch.setattr(harness, "ConnectionPool", FakePool)
    monkeypatch.setattr(harness, "PostgresSaver", FakeSaver)


def test_the_checkpoint_pool_settings(fakes):
    with harness.checkpoint_pool():
        [pool] = FakePool.opened
        assert pool.conninfo == "postgresql://u:p@pooler.example.com/db"
        assert (pool.settings["min_size"], pool.settings["max_size"]) == (1, 4)
        assert pool.settings["timeout"] == 120
        kwargs = pool.settings["kwargs"]
        assert (kwargs["autocommit"], kwargs["prepare_threshold"]) == (True, 0)
        assert kwargs["row_factory"] is harness.dict_row
        assert kwargs["options"] == "-c search_path=undercover"
        assert "undercover" in repr(pool.statements[0])
        [saver] = FakeSaver.made
        assert (saver.pool, saver.set_up) == (pool, True)


def test_each_claim_graph_has_a_saver_of_its_own(fakes, monkeypatch):
    built = []
    monkeypatch.setattr(
        harness,
        "claim_graph",
        lambda llm, instructions, saver: built.append((llm, instructions, saver)),
    )
    model = stub()
    with harness.checkpoint_pool() as pool:
        new_graph = harness.claim_graphs(model, "Decide the claim.", pool)
        new_graph()
        new_graph()
    [first, second] = built
    assert first[0] is second[0] is model
    assert first[1] == second[1] == "Decide the claim."
    assert first[2] is not second[2]
    assert {first[2].pool, second[2].pool} == {pool}
    assert [saver.set_up for saver in FakeSaver.made] == [True, False, False]


def test_command_line_works_one_claim(monkeypatch, capsys):
    pool = object()
    built = []
    monkeypatch.setattr(cli, "checkpoint_pool", lambda: nullcontext(pool))

    def current_claim_agents(on):
        built.append(on)
        graph = cast(harness.ClaimGraph, "graph")
        return harness.ClaimAgents(1, "stub", "default", lambda: graph)

    monkeypatch.setattr(cli, "current_claim_agents", current_claim_agents)
    worked = []
    monkeypatch.setattr(cli, "work_claim", lambda *args: worked.append(args))
    cli.main(["CLM-1001"])
    assert built == [pool]
    assert worked == [("CLM-1001", None, "graph")]

    def refuse(claim_id, run_id, graph):
        raise Refused(409, f"Claim {claim_id} is not waiting")

    monkeypatch.setattr(cli, "work_claim", refuse)
    with pytest.raises(SystemExit) as refused:
        cli.main(["CLM-1003"])
    assert refused.value.code == 1
    assert capsys.readouterr().err == (
        "CLM-1003  not started: 409: Claim CLM-1003 is not waiting\n"
    )


def test_command_line_needs_a_claim(capsys):
    with pytest.raises(SystemExit):
        cli.main([])
    assert "the following arguments are required: claim_id" in capsys.readouterr().err


def test_a_versions_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    version = {"model": "google/gemini-3.5-flash-lite", "reasoning_effort": "minimal"}
    llm = models.model(version)
    assert (llm.model_name, llm.reasoning_effort) == tuple(version.values())
    assert llm.request_timeout == 120
    assert llm.max_retries == 5
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert models.model(version).model_name == "openrouter/free"
    assert models.model(version).reasoning_effort is None


def test_a_versions_claim_agents(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    agents = harness.claim_agents_of(1, NO_POOL)
    assert agents.setup(7) == {
        "agents": 7,
        "version": 1,
        "model": "openai/gpt-6-luna",
        "reasoning_effort": "low",
    }
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    free = harness.claim_agents_of(1, NO_POOL)
    assert (free.model, free.reasoning_effort) == ("openrouter/free", "default")
