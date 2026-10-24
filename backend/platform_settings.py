"""The backend's operations on the platform's settings, which every handler can see
and a senior handler can change, and on the models the claim agent may use, which
are set in data/models.json."""

from fastapi import APIRouter
from sqlalchemy import insert, select

from backend.auth import Senior
from backend.database import now, settings
from backend.dependencies import Database
from backend.lookups import current_settings, models_allowed
from backend.models import AllowedModel, Settings, SettingsHistory, SettingsRequest

router = APIRouter()


@router.get("/api/settings", operation_id="get_settings")
def get_settings(db: Database) -> SettingsHistory:
    """Get the settings as they stand, and every change to them, newest first."""
    query = select(settings).order_by(settings.c.settings_id.desc())
    changes = [Settings(**row) for row in db.execute(query).mappings()]
    return SettingsHistory(current=changes[0], changes=changes)


@router.put("/api/settings", operation_id="update_settings")
def update_settings(
    request: SettingsRequest, handler: Senior, db: Database
) -> Settings:
    """Change the settings as a senior handler, keeping the change on record."""
    db.execute(
        insert(settings).values(
            **request.model_dump(), changed_by=handler.name, changed_at=now()
        )
    )
    return current_settings(db)


@router.get("/api/models", operation_id="list_models")
def list_models(db: Database) -> list[AllowedModel]:
    """List the models the claim agent may use, with their efforts and prices."""
    return models_allowed(db)
