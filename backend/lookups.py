"""What more than one of the backend's modules looks up: a run, the current
settings, the models allowed and the claim agent's versions, with the messages for
what isn't found."""

import os

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, select

from backend.database import agent_versions, allowed_models, runs, settings
from backend.models import AgentVersion, AllowedModel, Settings, VersionVerdict

RUN_NOT_FOUND = "Run {run_id} not found"
CLAIM_NOT_FOUND = "Claim {claim_id} not found"
VERSION_NOT_FOUND = "Version {version} not found"
# With MODEL_NAME set, as for students on free models, that model is the only one
# allowed, at its default reasoning effort and a price of 0. The agent records a
# run's effort with the same word.
DEFAULT_EFFORT = "default"


def run_row(db: Connection, run_id: str) -> RowMapping:
    """Return one run's row, or raise a 404."""
    row = db.execute(select(runs).where(runs.c.run_id == run_id)).mappings().first()
    if row is None:
        raise HTTPException(404, RUN_NOT_FOUND.format(run_id=run_id))
    return row


def current_settings(db: Connection) -> Settings:
    """Return the settings as they stand: the newest version of them."""
    query = select(settings).order_by(settings.c.settings_id.desc()).limit(1)
    return Settings(**db.execute(query).mappings().one())


def models_allowed(db: Connection) -> list[AllowedModel]:
    """Return the models the claim agent may use, with their reasoning efforts and
    prices, or MODEL_NAME alone when it is set."""
    if name := os.getenv("MODEL_NAME"):
        return [
            AllowedModel(
                model=name,
                reasoning_efforts=[DEFAULT_EFFORT],
                input_price=0,
                output_price=0,
            )
        ]
    rows = db.execute(select(allowed_models).order_by(allowed_models.c.position))
    return [AllowedModel(**row) for row in rows.mappings()]


def find_version(db: Connection, version: int) -> AgentVersion:
    """Return one version of the claim agent, or raise a 404."""
    query = select(agent_versions).where(agent_versions.c.version == version)
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, VERSION_NOT_FOUND.format(version=version))
    return AgentVersion(**row)


def current_version(db: Connection) -> AgentVersion:
    """Return the version every dispatch uses: the newest one a round kept."""
    query = (
        select(agent_versions)
        .where(agent_versions.c.verdict == VersionVerdict.KEPT)
        .order_by(agent_versions.c.version.desc())
        .limit(1)
    )
    return AgentVersion(**db.execute(query).mappings().one())
