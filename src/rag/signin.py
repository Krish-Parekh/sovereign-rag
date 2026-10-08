import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

REDIRECT_URI = "http://localhost:8765/callback"
SCOPES = "openid sovereign-rag/ask"


@dataclass(frozen=True)
class Pkce:
    verifier: str
    challenge: str


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def new_pkce() -> Pkce:
    verifier = secrets.token_urlsafe(64)
    return Pkce(verifier=verifier, challenge=challenge_for(verifier))


def authorize_url(domain: str, client_id: str, pkce: Pkce, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{domain}/oauth2/authorize?{query}"


def code_from_callback(path: str, expected_state: str) -> str:
    query = parse_qs(urlsplit(path).query)
    states = query.get("state", [])
    codes = query.get("code", [])
    if states != [expected_state] or len(codes) != 1:
        raise ValueError("callback has no code or a wrong state")
    return codes[0]


def exchange_code(client: httpx.Client, domain: str, client_id: str, code: str, pkce: Pkce) -> str:
    response = client.post(
        f"{domain}/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": pkce.verifier,
        },
    )
    response.raise_for_status()
    return str(response.json()["access_token"])
