"""The UnderCover database, seeded from the business data in data/.

The same tables and queries serve Postgres on Supabase, when DATABASE_URL is set, and
SQLite otherwise, as in the tests.
"""

import json
import os
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Connection,
    Engine,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    create_engine,
    insert,
    inspect,
    select,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema

from backend.models import EvaluationSet, Status, VersionVerdict

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INSTRUCTIONS = Path(__file__).parent / "instructions"
# Who made the first version of the agent and the settings: the business itself.
UNDERCOVER = "UnderCover"
FIRST_VERSION = {
    "version": 1,
    "model": "openai/gpt-6-luna",
    "reasoning_effort": "low",
    "based_on": None,
    "change": "The first version",
    "reason": "The claim agent as it was on Week 2 Day 4",
    "proposed_by": UNDERCOVER,
    "approved_by": UNDERCOVER,
    "round_id": None,
    "proposal_id": None,
    "verdict": VersionVerdict.KEPT,
}
DOCUMENTS = {"policy_wording": "Policy wording", "claims_manual": "Claims manual"}
HELD_OUT_CLAIMS = "evals/held_out_claims.json"
SCHEMA = "undercover"
CONNECTIONS = 4
CONNECTION_WAIT = 120
# Tables of earlier versions, dropped before the others, since on Postgres a foreign
# key of theirs would stop the tables they refer to being dropped.
RETIRED = ["todos"]

metadata = MetaData()

# Each change to the settings is a new row; the newest is the current one.
settings = Table(
    "settings",
    metadata,
    Column("settings_id", Integer, primary_key=True),
    Column("payout_approval_limit", Float, nullable=False),
    Column("objectives", JSON, nullable=False),
    Column("noise", JSON, nullable=False),
    Column("tolerance", JSON, nullable=False),
    Column("spending_limit", Float, nullable=False),
    Column("agents", Integer, nullable=False),
    Column("changed_by", Text, nullable=False),
    Column("changed_at", Text, nullable=False),
)
plans = Table("plans", metadata, Column("plans", JSON, nullable=False))
allowed_models = Table(
    "allowed_models",
    metadata,
    Column("model", Text, primary_key=True),
    Column("position", Integer, nullable=False),
    Column("reasoning_efforts", JSON, nullable=False),
    Column("input_price", Float, nullable=False),
    Column("output_price", Float, nullable=False),
)
# The improver's recipe, in versions; a round follows the newest.
recipes = Table(
    "recipes",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("recipe", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("proposed_by", Text, nullable=False),
    Column("approved_by", Text, nullable=False),
    Column("approved_at", Text, nullable=False),
    Column("round_id", Text, ForeignKey("rounds.round_id")),
    # The approved proposal it was made from, once only.
    Column("proposal_id", Integer, ForeignKey("proposals.proposal_id"), unique=True),
    Column("created_at", Text, nullable=False),
)
# A round of improvement, with the settings and models allowed it started with.
rounds = Table(
    "rounds",
    metadata,
    Column("number", Integer, primary_key=True),
    Column("round_id", Text, nullable=False, unique=True),
    Column("thread_id", Text, nullable=False),
    Column("stage", Text, nullable=False),
    Column("recipe_version", Integer, nullable=False),
    Column("settings", JSON, nullable=False),
    Column("models_allowed", JSON, nullable=False),
    Column("version_before", Integer, nullable=False),
    Column("version_tried", Integer),
    Column("reason", Text),
    Column("scores_before", JSON),
    Column("scores_after", JSON),
    Column("verdict", Text),
    Column("why", Text),
    Column("started_by", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("stopped_by", Text),
    Column("finished_at", Text),
)
# What the improver proposed in a round, and what a handler decided.
proposals = Table(
    "proposals",
    metadata,
    Column("proposal_id", Integer, primary_key=True),
    Column("round_id", Text, ForeignKey("rounds.round_id"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("based_on", Integer, nullable=False),
    Column("instructions", Text),
    Column("model", Text),
    Column("reasoning_effort", Text),
    Column("recipe", Text),
    Column("decided_by", Text),
    Column("decided_at", Text),
    Column("rejection", Text),
    Column("created_at", Text, nullable=False),
)
round_model_calls = Table(
    "round_model_calls",
    metadata,
    Column("round_model_call_id", Integer, primary_key=True),
    Column("round_id", Text, ForeignKey("rounds.round_id"), nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost", Float, nullable=False),
    Column("created_at", Text, nullable=False),
)
# The claim agent's configuration, in versions; the current one is the newest kept.
agent_versions = Table(
    "agent_versions",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("instructions", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("reasoning_effort", Text, nullable=False),
    # The version it was proposed against, and is shown changing.
    Column("based_on", Integer),
    Column("change", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("proposed_by", Text, nullable=False),
    Column("approved_by", Text, nullable=False),
    Column("approved_at", Text, nullable=False),
    Column("round_id", Text, ForeignKey("rounds.round_id")),
    Column("proposal_id", Integer, ForeignKey("proposals.proposal_id"), unique=True),
    Column("verdict", Text),
    Column("created_at", Text, nullable=False),
)
documents = Table(
    "documents",
    metadata,
    Column("name", Text, primary_key=True),
    Column("position", Integer, nullable=False),
    Column("title", Text, nullable=False),
    Column("text", Text, nullable=False),
)
handlers = Table(
    "handlers",
    metadata,
    Column("handler_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("email", Text, nullable=False, unique=True),
    Column("can_approve_over_limit", Boolean, nullable=False),
)
customers = Table(
    "customers",
    metadata,
    Column("customer_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("record", JSON, nullable=False),
)
policies = Table(
    "policies",
    metadata,
    Column("policy_id", Text, primary_key=True),
    Column("record", JSON, nullable=False),
)
claims = Table(
    "claims",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("customer_id", Text, ForeignKey("customers.customer_id"), nullable=False),
    Column("record", JSON, nullable=False),
    Column("status", Text, nullable=False),
    Column("thread_id", Text),
    Column("attempts", Integer, nullable=False),
    Column("evaluation_id", Text, ForeignKey("runs.run_id")),
    Column("copy_of", Text),
)
held_out_claims = Table(
    "held_out_claims",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("record", JSON, nullable=False),
)
handler_decisions = Table(
    "handler_decisions",
    metadata,
    Column("evaluation_set", Text, primary_key=True),
    Column("claim_id", Text, primary_key=True),
    Column("decision", Text, nullable=False),
    Column("payout", Float, nullable=False),
    Column("tiny", Boolean, nullable=False),
    # For the judge, and for the improver's view of the evaluation set.
    Column("reason", Text, nullable=False),
    Column("reference", Text, nullable=False),
)
decisions = Table(
    "decisions",
    metadata,
    Column("claim_id", Text, ForeignKey("claims.claim_id"), primary_key=True),
    Column("decision", Text, nullable=False),
    Column("payout", Float, nullable=False),
    Column("section", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("decided_at", Text, nullable=False),
    Column("signed_off_by", Text),
    Column("signed_off_at", Text),
)
payments = Table(
    "payments",
    metadata,
    Column("claim_id", Text, ForeignKey("claims.claim_id"), primary_key=True),
    Column("amount", Float, nullable=False),
    Column("paid_at", Text, nullable=False),
)
steps = Table(
    "steps",
    metadata,
    Column("step_id", Integer, primary_key=True),
    Column("claim_id", Text, ForeignKey("claims.claim_id"), nullable=False),
    Column("thread_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)
runs = Table(
    "runs",
    metadata,
    Column("number", Integer, primary_key=True),
    Column("run_id", Text, nullable=False, unique=True),
    Column("kind", Text, nullable=False),
    Column("agents", Integer, nullable=False),
    Column("version", Integer, ForeignKey("agent_versions.version"), nullable=False),
    Column("round_id", Text, ForeignKey("rounds.round_id")),
    Column("model", Text, nullable=False),
    Column("reasoning_effort", Text, nullable=False),
    Column("evaluation_set", Text),
    Column("tiny", Boolean),
    Column("status", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("finished_at", Text),
    Column("summary", JSON),
)
# The judge's grade on each copy it graded, with the call's cost. A copy it
# couldn't grade has no row.
grades = Table(
    "grades",
    metadata,
    Column("claim_id", Text, ForeignKey("claims.claim_id"), primary_key=True),
    Column("run_id", Text, ForeignKey("runs.run_id"), nullable=False),
    Column("score", Float, nullable=False),
    Column("letter", Text, nullable=False),
    Column("same_grounds", Float, nullable=False),
    Column("same_section", Float, nullable=False),
    Column("cost", Float, nullable=False),
)
run_claims = Table(
    "run_claims",
    metadata,
    Column("run_id", Text, ForeignKey("runs.run_id"), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("claim_id", Text, ForeignKey("claims.claim_id"), nullable=False),
)
model_calls = Table(
    "model_calls",
    metadata,
    Column("model_call_id", Integer, primary_key=True),
    Column("claim_id", Text, ForeignKey("claims.claim_id"), nullable=False),
    Column("thread_id", Text, nullable=False),
    Column("run_id", Text, ForeignKey("runs.run_id")),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost", Float, nullable=False),
    Column("created_at", Text, nullable=False),
)
work_times = Table(
    "work_times",
    metadata,
    Column("work_time_id", Integer, primary_key=True),
    Column("claim_id", Text, ForeignKey("claims.claim_id"), nullable=False),
    Column("thread_id", Text, nullable=False),
    Column("run_id", Text, ForeignKey("runs.run_id")),
    Column("started_at", Text, nullable=False),
    Column("seconds", Float, nullable=False),
)


class LabeledSet(NamedTuple):
    """A set of claims our handlers have decided: the table its claims are kept in,
    and the file in data/evals/ with the handlers' decisions, which only seeding
    reads."""

    claims: Table
    decisions: str


LABELED_SETS = {
    EvaluationSet.EVALUATION: LabeledSet(claims, "evals/decisions.json"),
    EvaluationSet.HELD_OUT: LabeledSet(
        held_out_claims, "evals/held_out_decisions.json"
    ),
}

claim_view = (
    select(
        claims.c.claim_id,
        claims.c.record,
        claims.c.status,
        claims.c.thread_id,
        claims.c.attempts,
        claims.c.evaluation_id,
        claims.c.copy_of,
        customers.c.name.label("customer_name"),
        decisions.c.decision,
        decisions.c.payout,
        decisions.c.section,
        decisions.c.reason,
        decisions.c.decided_at,
        decisions.c.signed_off_by,
        decisions.c.signed_off_at,
        payments.c.amount,
        payments.c.paid_at,
    )
    .join(customers, customers.c.customer_id == claims.c.customer_id)
    .outerjoin(decisions, decisions.c.claim_id == claims.c.claim_id)
    .outerjoin(payments, payments.c.claim_id == claims.c.claim_id)
)


def stamp(moment: datetime) -> str:
    """Write a moment in UTC to the second, as every record has it."""
    return moment.isoformat(timespec="seconds")


def now() -> str:
    """Return the current time in UTC, to the second."""
    return stamp(datetime.now(UTC))


def database_url() -> URL:
    """Return Postgres at DATABASE_URL, through psycopg and in our own schema, or
    SQLite at UNDERCOVER_DB or undercover.db."""
    if url := os.getenv("DATABASE_URL"):
        postgres = make_url(url).set(drivername="postgresql+psycopg")
        return postgres.update_query_dict({"options": f"-c search_path={SCHEMA}"})
    path = os.getenv("UNDERCOVER_DB", str(ROOT / "undercover.db"))
    return URL.create("sqlite", database=path)


def on_postgres(url: URL) -> bool:
    """Say whether a database is Postgres rather than SQLite."""
    return url.get_backend_name() == "postgresql"


@cache
def engine_for(url: URL) -> Engine:
    """Open a database: Postgres with at most CONNECTIONS connections, waiting up to
    CONNECTION_WAIT seconds for one, or SQLite with a connection for each request."""
    if on_postgres(url):
        return create_engine(
            url,
            pool_size=CONNECTIONS,
            max_overflow=0,
            pool_timeout=CONNECTION_WAIT,
            pool_pre_ping=True,
        )
    return create_engine(url, poolclass=NullPool)


def engine() -> Engine:
    """Return the backend's database."""
    return engine_for(database_url())


def location(db: Engine) -> str:
    """Say where a database is, for a person to read."""
    if on_postgres(db.url):
        return f"the {SCHEMA} schema on Postgres"
    return Path(str(db.url.database)).name


def is_seeded(db: Engine) -> bool:
    """Say whether the database has its tables."""
    return inspect(db).has_table("claims")


def load(name: str) -> Any:
    """Read one of the JSON files in data/."""
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def waiting_claim(record: dict[str, Any], **columns: Any) -> dict[str, Any]:
    """Return the row of a claim waiting in the queue, never started, with any other
    columns given."""
    return {
        "claim_id": record["claim_id"],
        "customer_id": record["customer_id"],
        "record": record,
        "status": Status.WAITING,
        "thread_id": None,
        "attempts": 0,
    } | columns


def seed(db: Engine) -> dict[str, int]:
    """Build the tables afresh from data/ and count what they hold."""
    handler_rows = load("handlers.json")
    customer_rows = load("customers.json")
    policy_rows = load("policies.json")
    claim_rows = load("claims.json")
    with db.begin() as connection:
        if on_postgres(db.url):
            connection.execute(CreateSchema(SCHEMA, if_not_exists=True))
        for name in RETIRED:
            Table(name, MetaData()).drop(connection, checkfirst=True)
        metadata.drop_all(connection)
        metadata.create_all(connection)
        seed_settings(connection)
        seed_models(connection)
        seed_configuration(connection)
        connection.execute(
            insert(documents),
            [
                {
                    "name": name,
                    "position": position,
                    "title": title,
                    "text": (DATA / f"{name}.md").read_text(encoding="utf-8"),
                }
                for position, (name, title) in enumerate(DOCUMENTS.items())
            ],
        )
        connection.execute(
            insert(handlers),
            [
                {
                    "handler_id": h["handler_id"],
                    "name": h["name"],
                    "role": h["role"],
                    "email": h["email"],
                    "can_approve_over_limit": h["can_approve_over_limit"],
                }
                for h in handler_rows
            ],
        )
        connection.execute(
            insert(customers),
            [
                {"customer_id": c["customer_id"], "name": c["name"], "record": c}
                for c in customer_rows
            ],
        )
        connection.execute(
            insert(policies),
            [{"policy_id": p["policy_id"], "record": p} for p in policy_rows],
        )
        connection.execute(insert(claims), [waiting_claim(c) for c in claim_rows])
        labeled = seed_evaluations(connection)
    return {
        "claims": len(claim_rows),
        "policies": len(policy_rows),
        "customers": len(customer_rows),
        "handlers": len(handler_rows),
    } | labeled


def seed_settings(connection: Connection) -> None:
    """Store the first settings, from company.json and improvement.json, and the
    plans."""
    connection.execute(
        insert(settings),
        {
            "payout_approval_limit": load("company.json")["payout_approval_limit"],
            **load("improvement.json"),
            "changed_by": UNDERCOVER,
            "changed_at": now(),
        },
    )
    connection.execute(insert(plans), {"plans": load("plans.json")})


def seed_models(connection: Connection) -> None:
    """Store the models the claim agent may use, from models.json."""
    connection.execute(
        insert(allowed_models),
        [
            {"position": position, **model}
            for position, model in enumerate(load("models.json"))
        ],
    )


def seed_configuration(connection: Connection) -> None:
    """Store the claim agent's first version, from its instructions file, and the
    improver's first recipe, the lab's, from the file beside it."""
    instructions = (INSTRUCTIONS / "claim.md").read_text(encoding="utf-8")
    stamped = now()
    connection.execute(
        insert(agent_versions),
        FIRST_VERSION
        | {"instructions": instructions, "approved_at": stamped, "created_at": stamped},
    )
    connection.execute(
        insert(recipes),
        {
            "version": 1,
            "recipe": (INSTRUCTIONS / "recipe.md").read_text(encoding="utf-8"),
            "reason": "The lab's first recipe, which adds a rule for each mistake",
            "proposed_by": UNDERCOVER,
            "approved_by": UNDERCOVER,
            "approved_at": stamped,
            "round_id": None,
            "proposal_id": None,
            "created_at": stamped,
        },
    )


def seed_evaluations(connection: Connection) -> dict[str, int]:
    """Store the held-out claims, out of the queue, and the handlers' decisions on
    both labeled sets, and count them."""
    held_out = load(HELD_OUT_CLAIMS)
    connection.execute(
        insert(held_out_claims),
        [{"claim_id": c["claim_id"], "record": c} for c in held_out],
    )
    rows = [
        {
            "evaluation_set": evaluation_set,
            "claim_id": d["claim_id"],
            "decision": d["decision"],
            "payout": d["payout"],
            "tiny": d["tiny"],
            "reason": d["reason"],
            "reference": d["reference"],
        }
        for evaluation_set, labeled in LABELED_SETS.items()
        for d in load(labeled.decisions)
    ]
    connection.execute(insert(handler_decisions), rows)
    return {"held_out_claims": len(held_out), "handler_decisions": len(rows)}
