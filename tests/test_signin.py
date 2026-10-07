from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from rag.signin import REDIRECT_URI, Pkce, authorize_url, challenge_for, code_from_callback, exchange_code, new_pkce

DOMAIN = "https://sovereign-rag-1.auth.ap-southeast-2.amazoncognito.com"


def test_challenge_matches_rfc7636_example() -> None:
    assert challenge_for("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_new_pkce_verifier_length_is_valid_and_random() -> None:
    first, second = new_pkce(), new_pkce()

    assert 43 <= len(first.verifier) <= 128
    assert first.verifier != second.verifier
    assert first.challenge == challenge_for(first.verifier)


def test_authorize_url_requests_code_with_s256_and_ask_scope() -> None:
    pkce = Pkce(verifier="v" * 50, challenge="c")

    url = urlsplit(authorize_url(DOMAIN, "client1", pkce, "state1"))
    query = parse_qs(url.query)

    assert f"{url.scheme}://{url.netloc}{url.path}" == f"{DOMAIN}/oauth2/authorize"
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == ["c"]
    assert query["scope"] == ["openid sovereign-rag/ask"]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["state"] == ["state1"]


def test_callback_returns_code_when_state_matches() -> None:
    assert code_from_callback("/callback?code=abc&state=s1", "s1") == "abc"


@pytest.mark.parametrize(
    "path", ["/callback?code=abc&state=other", "/callback?state=s1", "/callback?error=access_denied"]
)
def test_callback_rejects_wrong_state_or_missing_code(path: str) -> None:
    with pytest.raises(ValueError, match="callback"):
        code_from_callback(path, "s1")


def test_exchange_sends_verifier_and_returns_access_token() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "at",
                "id_token": "it",
                "refresh_token": "rt",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        tokens = exchange_code(client, DOMAIN, "client1", "code1", Pkce(verifier="ver", challenge="c"))

    assert tokens.access_token == "at"
    assert str(seen[0].url) == f"{DOMAIN}/oauth2/token"
    form = parse_qs(seen[0].content.decode())
    assert form["grant_type"] == ["authorization_code"]
    assert form["code_verifier"] == ["ver"]
    assert form["redirect_uri"] == [REDIRECT_URI]
