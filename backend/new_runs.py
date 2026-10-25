"""Recording a new run: a dispatch, or an evaluation with a waiting copy of each
claim of its labeled set, which the runs router and the rounds router both make."""

import uuid
from typing import Any

from sqlalchemy import Connection, RowMapping, delete, insert, select

from backend.database import (
    LABELED_SETS,
    claims,
    handler_decisions,
    now,
    run_claims,
    runs,
    waiting_claim,
)
from backend.lookups import run_row
from backend.models import EvaluationSet, RunKind, RunStatus

# A copy's id is its original's with the evaluation's number, such as CLM-1104-E7.
COPY_ID = "{claim_id}-E{number}"


def new_run(db: Connection, kind: RunKind, fields: dict[str, Any]) -> RowMapping:
    """Record a new run, running, and return its row."""
    run_id = str(uuid.uuid4())
    db.execute(
        insert(runs).values(
            run_id=run_id,
            kind=kind,
            **fields,
            status=RunStatus.RUNNING,
            started_at=now(),
        )
    )
    return run_row(db, run_id)


def put_claims(db: Connection, run_id: str, claim_ids: list[str]) -> None:
    """Record a run's claims in order, in place of any recorded before."""
    db.execute(delete(run_claims).where(run_claims.c.run_id == run_id))
    if claim_ids:
        db.execute(
            insert(run_claims),
            [
                {"run_id": run_id, "position": position, "claim_id": claim_id}
                for position, claim_id in enumerate(claim_ids)
            ],
        )


def originals(
    db: Connection, evaluation_set: EvaluationSet, tiny: bool
) -> list[dict[str, Any]]:
    """Return the records of a labeled set's claims, all or its tiny ones, oldest
    submitted first."""
    chosen = select(handler_decisions.c.claim_id).where(
        handler_decisions.c.evaluation_set == evaluation_set
    )
    if tiny:
        chosen = chosen.where(handler_decisions.c.tiny)
    table = LABELED_SETS[evaluation_set].claims
    records = db.execute(select(table.c.record).where(table.c.claim_id.in_(chosen)))
    return sorted(records.scalars(), key=lambda r: (r["submitted_on"], r["claim_id"]))


def make_copies(
    db: Connection, run: RowMapping, records: list[dict[str, Any]]
) -> list[str]:
    """Copy each claim, waiting, as the evaluation's own, with a new id in its record
    too, and return the copies' ids in order."""
    copies = [
        record
        | {
            "claim_id": COPY_ID.format(
                claim_id=record["claim_id"], number=run["number"]
            )
        }
        for record in records
    ]
    db.execute(
        insert(claims),
        [
            waiting_claim(
                copy, evaluation_id=run["run_id"], copy_of=original["claim_id"]
            )
            for copy, original in zip(copies, records, strict=True)
        ],
    )
    return [copy["claim_id"] for copy in copies]


def new_evaluation(db: Connection, fields: dict[str, Any]) -> RowMapping:
    """Record a new evaluation, running, with a waiting copy of each of its set's
    claims, all or its tiny ones, in order."""
    row = new_run(db, RunKind.EVALUATION, fields)
    records = originals(db, fields["evaluation_set"], fields["tiny"])
    put_claims(db, row["run_id"], make_copies(db, row, records))
    return row
