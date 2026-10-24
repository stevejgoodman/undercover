"""The backend's operations on the claim agent's configuration: its instructions,
model and reasoning effort, kept in versions. The claim agent fetches its version
with get_agent_version, which holds no scores; the dashboard reads the rest."""

from fastapi import APIRouter
from sqlalchemy import Connection, select

from backend.database import agent_versions
from backend.dependencies import Database
from backend.diffs import diff
from backend.documents import contents
from backend.lookups import current_version, find_version
from backend.models import (
    AgentConfiguration,
    AgentVersion,
    VersionDetails,
    VersionSummary,
)
from backend.run_views import Expected, expected_answers, version_scores

router = APIRouter()


def summary(
    db: Connection, version: AgentVersion, current: int, expected: Expected
) -> VersionSummary:
    """A version with its scores, and whether it is the current one."""
    return VersionSummary(
        **version.model_dump(),
        current=version.version == current,
        scores=version_scores(db, version.version, expected),
    )


@router.get("/api/configuration/current", operation_id="get_current_version")
def get_current_version(db: Database) -> AgentVersion:
    """Get the version every dispatch uses, without its scores."""
    return current_version(db)


@router.get(
    "/api/configuration/versions/{version}/agent", operation_id="get_agent_version"
)
def get_agent_version(version: int, db: Database) -> AgentConfiguration:
    """Get what the claim agent works from: its instructions, model and effort."""
    found = find_version(db, version)
    return AgentConfiguration(
        version=found.version,
        instructions=f"{found.instructions}\n{contents(db)}",
        model=found.model,
        reasoning_effort=found.reasoning_effort,
    )


@router.get("/api/configuration/versions", operation_id="list_versions")
def list_versions(db: Database) -> list[VersionSummary]:
    """List every version, newest first, with its scores on both sets."""
    query = select(agent_versions).order_by(agent_versions.c.version.desc())
    current, expected = current_version(db).version, expected_answers(db)
    return [
        summary(db, AgentVersion(**row), current, expected)
        for row in db.execute(query).mappings()
    ]


@router.get("/api/configuration/versions/{version}", operation_id="get_version")
def get_version(version: int, db: Database) -> VersionDetails:
    """Get a version with its scores and what it changed from its base version."""
    found = find_version(db, version)
    current, expected = current_version(db).version, expected_answers(db)
    changes = []
    if found.based_on is not None:
        before = find_version(db, found.based_on).instructions
        changes = diff(before, found.instructions)
    return VersionDetails(
        **summary(db, found, current, expected).model_dump(), diff=changes
    )
