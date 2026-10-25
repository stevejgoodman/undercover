"""The FastAPI dependencies the backend's routers share."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Connection, Engine

from backend.database import engine


def database() -> Iterator[Connection]:
    """Open the database for one request, in a transaction committed at its end."""
    with engine().begin() as connection:
        yield connection


# Committed before the response is sent and before any background task runs.
Database = Annotated[Connection, Depends(database, scope="function")]

# For an operation that waits on something slow between its reads and its writes,
# and so opens a short transaction for each.
DatabaseEngine = Annotated[Engine, Depends(engine)]
