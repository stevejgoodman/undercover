"""The handler signed in to the dashboard, as Supabase Auth vouches for them: the
backend checks each sign-in against the project's public keys and finds the handler
by the email address in it."""

import os
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from backend.database import handlers
from backend.dependencies import Database
from backend.lookups import current_settings
from backend.models import Handler
from backend.views import dollars

# PyJWT needs an address to start with, so with VITE_SUPABASE_URL unset, as in the
# unit tests, it gets Supabase's own address on this computer, where nothing runs.
SUPABASE_URL = os.getenv("VITE_SUPABASE_URL", "http://127.0.0.1:54321")
PUBLIC_KEYS = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
ISSUER = f"{SUPABASE_URL}/auth/v1"
AUDIENCE = "authenticated"
# Supabase signs with an asymmetric key, so no secret is needed to check a sign-in.
ALGORITHMS = ["ES256", "RS256"]
KEYS_TIMEOUT = 5
NOT_SIGNED_IN = "Please sign in"
NO_KEYS = "The sign-in can't be checked, because Supabase Auth can't be reached"
CANT_SIGN_OFF = "{name} can't sign off payouts over {limit}"
SENIOR_ONLY = CANT_SIGN_OFF + ", so only a senior handler can do this"

keys = jwt.PyJWKClient(PUBLIC_KEYS, cache_keys=True, timeout=KEYS_TIMEOUT)
bearer = HTTPBearer(auto_error=False)


def email_of(token: str) -> str:
    """Check a sign-in against Supabase's public keys and return its email address,
    or raise a 401, or a 503 when the keys can't be fetched."""
    try:
        key = keys.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=ALGORITHMS,
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "email"]},
        )
    except jwt.PyJWKClientConnectionError as error:
        raise HTTPException(503, NO_KEYS) from error
    except jwt.PyJWTError as error:
        raise HTTPException(401, NOT_SIGNED_IN) from error
    return claims["email"]


def signed_in(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Database,
) -> Handler:
    """Return the handler signed in, or raise a 401 with no sign-in, or a 403 for a
    sign-in that isn't a handler's."""
    if credentials is None:
        raise HTTPException(401, NOT_SIGNED_IN)
    email = email_of(credentials.credentials)
    row = db.execute(select(handlers).where(handlers.c.email == email)).mappings()
    handler = row.first()
    if handler is None:
        raise HTTPException(403, f"No handler signs in as {email}")
    return Handler(**handler)


SignedIn = Annotated[Handler, Depends(signed_in)]


def senior(handler: SignedIn, db: Database) -> Handler:
    """Return the handler signed in if they can sign off payouts over the limit, who
    alone may change the agent or a setting, or raise a 403."""
    if not handler.can_approve_over_limit:
        limit = dollars(current_settings(db).payout_approval_limit)
        raise HTTPException(403, SENIOR_ONLY.format(name=handler.name, limit=limit))
    return handler


Senior = Annotated[Handler, Depends(senior)]
