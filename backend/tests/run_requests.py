"""Requests the backend's tests send to record runs, as the agent's service does."""


def create_dispatch(client, agents=3):
    return client.post(
        "/api/runs/dispatches",
        json={
            "agents": agents,
            "version": 1,
            "model": "openai/gpt-6-luna",
            "reasoning_effort": "low",
        },
    )


def dispatch_of(client, *claim_ids):
    """Create a dispatch and record its claims, and return its id."""
    run_id = create_dispatch(client).json()["run_id"]
    record_claims(client, run_id, *claim_ids)
    return run_id


def record_claims(client, run_id, *claim_ids):
    return client.put(f"/api/runs/{run_id}/claims", json={"claim_ids": claim_ids})


def finish(client, run_id):
    return client.post(f"/api/runs/{run_id}/finish")


def latest_dispatch(client):
    return client.get("/api/dispatches/latest").json()


def create_evaluation(client, evaluation_set="held_out", tiny=True, agents=5):
    return client.post(
        "/api/runs/evaluations",
        json={
            "evaluation_set": evaluation_set,
            "tiny": tiny,
            "agents": agents,
            "version": 1,
            "model": "openai/gpt-6-luna",
            "reasoning_effort": "low",
        },
    )


def get_evaluation(client, run_id):
    return client.get(f"/api/evaluations/{run_id}").json()


def queue(client):
    return client.get("/api/claims").json()
