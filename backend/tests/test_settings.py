import pytest

from backend.tests.claim_requests import decide, pay, start
from backend.tests.settings_requests import FIRST
from backend.tests.signing import MARCUS


def test_the_settings_start_with_the_labs_values(client):
    settings = client.get("/api/settings").json()
    current = settings["current"]
    assert {k: v for k, v in current.items() if k in FIRST} == FIRST
    assert current["changed_by"] == "UnderCover"
    assert settings["changes"] == [current]


def test_a_senior_handler_changes_the_settings(client):
    changed = client.put("/api/settings", json=FIRST | {"spending_limit": 0.75})
    assert changed.status_code == 200
    assert (changed.json()["spending_limit"], changed.json()["changed_by"]) == (
        0.75,
        "Dana Whitfield",
    )
    settings = client.get("/api/settings").json()
    assert settings["current"] == changed.json()
    assert [c["spending_limit"] for c in settings["changes"]] == [0.75, 0.5]


def test_only_a_senior_handler_changes_the_settings(client, client_as, anonymous):
    refused = client_as(MARCUS).put("/api/settings", json=FIRST | {"agents": 3})
    assert refused.status_code == 403
    assert refused.json()["detail"] == (
        "Marcus Oyelaran can't sign off payouts over $1,000.00, "
        "so only a senior handler can do this"
    )
    assert anonymous.put("/api/settings", json=FIRST).status_code == 401
    assert len(client.get("/api/settings").json()["changes"]) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"payout_approval_limit": 0},
        {"spending_limit": -1},
        {"agents": 26},
        {"noise": FIRST["noise"] | {"accuracy": -0.1}},
        {"objectives": {"accuracy": 1.5, "grade": 1.0}},
    ],
)
def test_settings_out_of_range_are_refused(client, bad):
    assert client.put("/api/settings", json=FIRST | bad).status_code == 422


def test_a_new_approval_limit_applies_to_the_next_decision(client):
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1350.0)
    client.put("/api/settings", json=FIRST | {"payout_approval_limit": 2000})
    start(client, "CLM-1008")
    decided = decide(client, "CLM-1008", "approve", 1350.0).json()
    assert decided["status"] == "in_progress"
    assert pay(client, "CLM-1008", 1350.0).json()["status"] == "decided"
    held = client.get("/api/claims/CLM-1002").json()
    assert held["status"] == "waiting_for_sign_off"


def test_the_models_allowed(client, monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    models = client.get("/api/models").json()
    assert [m["model"] for m in models] == [
        "openai/gpt-6-luna",
        "google/gemini-3.5-flash-lite",
        "deepseek/deepseek-v4.1-flash",
    ]
    assert models[0] == {
        "model": "openai/gpt-6-luna",
        "reasoning_efforts": ["low", "medium"],
        "input_price": 0.1,
        "output_price": 0.5,
    }
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert client.get("/api/models").json() == [
        {
            "model": "openrouter/free",
            "reasoning_efforts": ["default"],
            "input_price": 0,
            "output_price": 0,
        }
    ]
