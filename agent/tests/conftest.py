import threading
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.checkpoint.memory import InMemorySaver

from agent import client, dispatcher, harness, improver, service
from agent.tests.stubs import graph_on
from backend.main import app


@pytest.fixture(autouse=True)
def backend(monkeypatch):
    """Send the agent's requests to the test backend, at the same address."""
    test_backend = TestClient(app, base_url=str(client.backend.base_url))
    monkeypatch.setattr(client, "backend", test_backend)


class RecordRoots(BaseCallbackHandler):
    """Stands in for Langfuse's handler, keeping the metadata of each root run."""

    def __init__(self, roots: list[dict[str, Any]]) -> None:
        self.roots = roots

    def on_chain_start(self, serialized, inputs, *, parent_run_id=None, **kwargs):
        if parent_run_id is None:
            self.roots.append(dict(kwargs.get("metadata") or {}))


@pytest.fixture(autouse=True)
def traces(monkeypatch):
    """Keep Langfuse out of the tests, and record the root runs it would trace."""
    roots: list[dict[str, Any]] = []
    monkeypatch.setattr(harness, "CallbackHandler", lambda: RecordRoots(roots))
    monkeypatch.setattr(improver, "CallbackHandler", lambda: RecordRoots(roots))
    return roots


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    """Take the waits out of the dispatcher's RetryPolicy, keeping its tries, so the
    tests never sleep through the backoff. Returns the real policy."""
    real = dispatcher.RETRY
    monkeypatch.setattr(
        dispatcher, "RETRY", real._replace(initial_interval=0, jitter=False)
    )
    return real


@pytest.fixture
def serve():
    """Run the agent's service, without its lifespan, with claim agents on a stub
    model whose graphs share a saver."""

    def with_model(model, saver=None):
        saver = saver or InMemorySaver()
        agents = harness.ClaimAgents(
            1, "stub", "default", lambda: graph_on(model, saver)
        )
        service.app.dependency_overrides[service.build_claim_agents] = lambda: agents
        return TestClient(service.app)

    yield with_model
    service.app.dependency_overrides.clear()


@dataclass
class HeldRun:
    """A run the service is working, held open until the test releases it, and the
    claims being resumed that the service handed the dispatcher."""

    working: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    resuming: list[set[str]] = field(default_factory=list)


@pytest.fixture
def held_run(monkeypatch):
    """Hold each run the service starts open until the test releases it."""
    held = HeldRun()
    work_run = service.work_run

    def hold(run, work, resuming):
        held.resuming.append(resuming)
        held.working.set()
        held.release.wait(5)
        return work_run(run, work, resuming)

    monkeypatch.setattr(service, "work_run", hold)
    return held
