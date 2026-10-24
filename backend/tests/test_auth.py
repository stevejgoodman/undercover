import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from backend import auth
from backend.auth import AUDIENCE, ISSUER
from backend.tests.claim_requests import decide, sign_off, start
from backend.tests.signing import DANA, KEY, MARCUS, OTHER_KEY, bearer, token_for

ACTIONS = [
    ("POST", "/api/dispatches", {"agents": 3}),
    (
        "POST",
        "/api/evaluations",
        {"evaluation_set": "held_out", "tiny": True, "agents": 5},
    ),
    ("POST", "/api/claims/CLM-1002/sign-off", None),
]
CLAIMS = {"email": DANA, "aud": AUDIENCE, "iss": ISSUER}


def held_payout(client):
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1350.0)


def encoded(part):
    return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=")


def unsigned():
    claims = CLAIMS | {"exp": int(time.time()) + 60}
    return (
        encoded({"alg": "none", "typ": "JWT"}) + b"." + encoded(claims)
    ).decode() + "."


def keyed_with_the_public_key():
    """An attacker's token, signed with HS256 keyed by the public key, built by
    hand since PyJWT refuses to sign one."""
    public = KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    claims = CLAIMS | {"exp": int(time.time()) + 60}
    signed = encoded({"alg": "HS256", "typ": "JWT"}) + b"." + encoded(claims)
    signature = hmac.new(public, signed, hashlib.sha256).digest()
    return (signed + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()


def without(claim):
    claims = CLAIMS | {"exp": int(time.time()) + 60}
    claims.pop(claim)
    return jwt.encode(claims, KEY, algorithm="ES256")


@pytest.mark.parametrize("action", ACTIONS)
def test_a_signed_in_handler_can_act(client, agent_calls, action):
    method, path, body = action
    held_payout(client)
    assert client.request(method, path, json=body).status_code in (200, 202)
    assert len(agent_calls) == 1


@pytest.mark.parametrize(
    "refusal",
    [
        ({}, 401),
        (bearer("not a token"), 401),
        (bearer(token_for(DANA, seconds=-60)), 401),
        (bearer(token_for(DANA, audience="anon")), 401),
        (bearer(token_for(DANA, key=OTHER_KEY)), 401),
        (bearer(unsigned()), 401),
        (bearer(keyed_with_the_public_key()), 401),
        (bearer(without("email")), 401),
        (bearer(without("exp")), 401),
        (bearer(without("iss")), 401),
        (bearer(token_for("someone@else.example")), 403),
    ],
    ids=[
        "none",
        "garbled",
        "expired",
        "audience",
        "other key",
        "unsigned",
        "HS256",
        "no email",
        "no expiry",
        "no issuer",
        "not a handler",
    ],
)
@pytest.mark.parametrize("action", ACTIONS)
def test_every_action_needs_a_valid_sign_in(
    client, anonymous, agent_calls, refusal, action
):
    headers, status = refusal
    method, path, body = action
    held_payout(client)
    response = anonymous.request(method, path, json=body, headers=headers)
    assert response.status_code == status
    assert agent_calls == []
    decision = client.get("/api/claims/CLM-1002").json()["decision"]
    assert decision["signed_off_by"] is None


def test_a_sign_in_for_someone_who_isnt_a_handler(anonymous):
    response = anonymous.get(
        "/api/handlers/me", headers=bearer(token_for("someone@else.example"))
    )
    assert response.json()["detail"] == "No handler signs in as someone@else.example"


def test_a_sign_in_cant_be_checked_without_supabase(client, monkeypatch):
    class Unreachable:
        def get_signing_key_from_jwt(self, token):
            raise jwt.PyJWKClientConnectionError("Connection refused")

    monkeypatch.setattr(auth, "keys", Unreachable())
    response = client.get("/api/handlers/me")
    assert response.status_code == 503
    assert response.json()["detail"] == auth.NO_KEYS


def test_the_signed_in_handler(client, client_as):
    dana = client.get("/api/handlers/me").json()
    assert (dana["name"], dana["can_approve_over_limit"]) == ("Dana Whitfield", True)
    marcus = client_as(MARCUS).get("/api/handlers/me").json()
    assert (marcus["name"], marcus["can_approve_over_limit"]) == (
        "Marcus Oyelaran",
        False,
    )


def test_nobody_is_signed_in(anonymous):
    response = anonymous.get("/api/handlers/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Please sign in"


def test_the_handlers_emails_arent_listed(anonymous):
    assert anonymous.get("/api/handlers").status_code == 404


def test_the_agents_own_writes_need_no_sign_in(anonymous):
    assert start(anonymous, "CLM-1002").status_code == 200
    assert decide(anonymous, "CLM-1002", "approve", 1350.0).status_code == 200
    assert anonymous.post("/api/runs/stop").status_code == 200


def test_a_sign_off_records_the_handler_signed_in(client, client_as):
    held_payout(client)
    assert sign_off(client_as(MARCUS), "CLM-1002").status_code == 403
    claim = sign_off(client, "CLM-1002").json()
    assert claim["decision"]["signed_off_by"] == "Dana Whitfield"
