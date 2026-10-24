"""What a round of improvement has spent and has left of its limit, and what an
evaluation is likely to cost: the improver's own model calls, its evaluations'
model calls, and the judge's calls on them."""

from sqlalchemy import Connection, func, select, union_all

from backend.database import grades, model_calls, round_model_calls, run_claims, runs
from backend.models import AllowedModel, RunKind, RunStatus


def spent_by_round(db: Connection) -> dict[str, float]:
    """Return what each round has spent so far, in US dollars, in one query: the
    improver's calls, and the model's and the judge's in its evaluations."""
    in_runs = [
        select(runs.c.round_id, table.c.cost).join(
            table, table.c.run_id == runs.c.run_id
        )
        for table in (model_calls, grades)
    ]
    costs = union_all(
        select(round_model_calls.c.round_id, round_model_calls.c.cost), *in_runs
    ).subquery()
    query = select(costs.c.round_id, func.sum(costs.c.cost).label("spent")).group_by(
        costs.c.round_id
    )
    return {row["round_id"]: row["spent"] for row in db.execute(query).mappings()}


def spent(db: Connection, round_id: str) -> float:
    """Return what a round has spent so far, in US dollars."""
    return spent_by_round(db).get(round_id, 0.0)


def left(db: Connection, round_id: str, limit: float) -> float:
    """Return what's left of a round's spending limit."""
    return limit - spent(db, round_id)


def highest_cost_per_claim(db: Connection, model: str) -> float | None:
    """Return the most a claim has cost on a model in a finished evaluation, model
    and judge together, or nothing if the model has none yet."""
    finished = select(runs.c.run_id).where(
        runs.c.kind == RunKind.EVALUATION,
        runs.c.model == model,
        runs.c.status == RunStatus.FINISHED,
    )
    costs = union_all(
        *(select(table.c.run_id, table.c.cost) for table in (model_calls, grades))
    ).subquery()
    cost = (
        select(costs.c.run_id, func.sum(costs.c.cost).label("cost"))
        .group_by(costs.c.run_id)
        .subquery()
    )
    size = (
        select(run_claims.c.run_id, func.count().label("size"))
        .group_by(run_claims.c.run_id)
        .subquery()
    )
    query = (
        select(func.max(func.coalesce(cost.c.cost, 0) / size.c.size))
        .select_from(size)
        .outerjoin(cost, cost.c.run_id == size.c.run_id)
        .where(size.c.run_id.in_(finished))
    )
    return db.execute(query).scalar_one()


def price_ratio(new: AllowedModel, old: AllowedModel) -> float:
    """How many times dearer one model is than another, by the larger of the ratios
    of their input and output prices."""
    ratios = [
        new_price / old_price
        for new_price, old_price in (
            (new.input_price, old.input_price),
            (new.output_price, old.output_price),
        )
        if old_price > 0
    ]
    return max(ratios, default=0)


def estimate(
    db: Connection,
    claims: int,
    model: str,
    current_model: str,
    models: list[AllowedModel],
) -> float:
    """Return what an evaluation of a number of claims on a model is likely to cost:
    the claims times the highest cost per claim seen on it, or, for a model with
    no runs yet, the current model's scaled by their prices. With no runs on
    either, nothing can be estimated, and it's 0."""
    seen = highest_cost_per_claim(db, model)
    if seen is not None:
        return claims * seen
    current = highest_cost_per_claim(db, current_model)
    prices = {allowed.model: allowed for allowed in models}
    if current is None or model not in prices or current_model not in prices:
        return 0.0
    return claims * current * price_ratio(prices[model], prices[current_model])
