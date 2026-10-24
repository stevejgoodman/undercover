"""Fixtures for the backend's and the agent's tests."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import agent_service, auth
from backend.database import engine, seed
from backend.main import app
from backend.tests.signing import DANA, StandInKeys, signed_in_as


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    """Give every test its own freshly seeded SQLite database, never Postgres."""
    path = tmp_path / "undercover.db"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("UNDERCOVER_DB", str(path))
    seed(engine())
    return path


@pytest.fixture
def agent_answers(monkeypatch):
    """Answer the backend's calls to the agent's service with a handler of the test's
    own, in place of the service."""

    def answer_with(handler):
        transport = httpx.MockTransport(handler)
        stand_in = httpx.Client(
            base_url=agent_service.agent.base_url, transport=transport
        )
        monkeypatch.setattr(agent_service, "agent", stand_in)

    return answer_with


@pytest.fixture(autouse=True)
def agent_calls(agent_answers):
    """Stand in for the agent's service, keeping the path and the body of each call
    to it, or None for a call with no body."""
    calls: list[tuple[str, object]] = []

    def accept(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.url.path, body))
        return httpx.Response(202, json={"status": "accepted"})

    agent_answers(accept)
    return calls


@pytest.fixture(autouse=True)
def sign_ins(monkeypatch):
    """Check sign-ins against the tests' own key, never Supabase's."""
    monkeypatch.setattr(auth, "keys", StandInKeys())


@pytest.fixture
def client():
    """The backend, with Dana Whitfield, our senior handler, signed in."""
    return TestClient(app, headers=signed_in_as(DANA))


@pytest.fixture
def client_as():
    """The backend, with the handler with the email given signed in."""
    return lambda email: TestClient(app, headers=signed_in_as(email))


@pytest.fixture
def anonymous():
    """The backend, with nobody signed in."""
    return TestClient(app)
