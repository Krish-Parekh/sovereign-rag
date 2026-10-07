import base64
import hashlib
import secrets
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from pydantic import BaseModel

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
SCOPES = "openid sovereign-rag/ask"


@dataclass(frozen=True)
class Pkce:
    verifier: str
    challenge: str


class TokenResponse(BaseModel):
    access_token: str
    id_token: str | None = None
    refresh_token: str | None = None
    expires_in: int
    token_type: str


@dataclass
class Received:
    path: str = ""


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


def exchange_code(client: httpx.Client, domain: str, client_id: str, code: str, pkce: Pkce) -> TokenResponse:
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
    return TokenResponse.model_validate_json(response.content)


def wait_for_callback() -> str:
    received = Received()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            received.path = self.path
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Signed in. You can close this tab.")

        def log_message(self, format: str, *args: Any) -> None:
            return

    with HTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler) as server:
        while not received.path.startswith("/callback"):
            server.handle_request()
    return received.path
