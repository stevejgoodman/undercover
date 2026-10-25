"""Sign-ins for the tests, signed with a key of the tests' own in place of
Supabase's, so no test reaches Supabase Auth."""

import time
from typing import NamedTuple

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from backend.auth import AUDIENCE, ISSUER

DANA = "dana.whitfield@undercover.example"
MARCUS = "marcus.oyelaran@undercover.example"

KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


class SigningKey(NamedTuple):
    key: ec.EllipticCurvePublicKey


class StandInKeys:
    """Stands in for the client of Supabase's public keys, with the tests' key."""

    def get_signing_key_from_jwt(self, token: str) -> SigningKey:
        return SigningKey(KEY.public_key())


def token_for(
    email: str,
    key: ec.EllipticCurvePrivateKey = KEY,
    audience: str = AUDIENCE,
    seconds: int = 3600,
) -> str:
    """Sign a sign-in for an email address, as Supabase Auth would."""
    claims = {
        "email": email,
        "aud": audience,
        "iss": ISSUER,
        "exp": int(time.time()) + seconds,
    }
    return jwt.encode(claims, key, algorithm="ES256")


def bearer(token: str) -> dict[str, str]:
    """The headers of a request carrying a sign-in."""
    return {"Authorization": f"Bearer {token}"}


def signed_in_as(email: str) -> dict[str, str]:
    """The headers of a request from a handler signed in with their email."""
    return bearer(token_for(email))
