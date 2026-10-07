import json

import pytest

from rag.auth import caller_from_context, request_id_from_context


def _context(claims: dict[str, str]) -> str:
    return json.dumps({"requestId": "api-1", "authorizer": {"claims": claims}})


def test_caller_comes_from_authorizer_claims() -> None:
    caller = caller_from_context(_context({"sub": "sub-a", "scope": "sovereign-rag/ask"}))

    assert caller is not None
    assert caller.sub == "sub-a"


@pytest.mark.parametrize(
    "header",
    [None, "not json", json.dumps({"requestId": "api-1"}), _context({"scope": "x"}), _context({"sub": ""})],
)
def test_missing_or_malformed_context_has_no_caller(header: str | None) -> None:
    assert caller_from_context(header) is None


def test_request_id_comes_from_lambda_context() -> None:
    assert request_id_from_context(json.dumps({"request_id": "lambda-9", "deadline": 0})) == "lambda-9"


def test_request_id_is_generated_without_lambda_context() -> None:
    assert len(request_id_from_context(None)) == 26
