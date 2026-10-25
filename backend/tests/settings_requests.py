"""The settings the backend's tests start from and change: the lab's."""

FIRST = {
    "payout_approval_limit": 1000.0,
    "objectives": {"accuracy": 0.6, "grade": 1.0},
    "noise": {
        "accuracy": 0.1,
        "grade": 0.15,
        "model_cost_per_claim": 0.15,
        "seconds_per_claim": 0.15,
    },
    "tolerance": {
        "accuracy": 0.1,
        "grade": 0.15,
        "model_cost_per_claim": 1.0,
        "seconds_per_claim": 0.25,
    },
    "spending_limit": 0.5,
    "agents": 25,
}
