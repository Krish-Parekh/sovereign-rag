import json
from typing import Any

from aws_lambda_powertools import Logger
from pydantic import ValidationError

from rag.answering import answer, caller_from_claims
from rag.schemas import AskRequest

logger = Logger(service="sovereign-rag")


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    caller = caller_from_claims(event["requestContext"]["authorizer"]["claims"])
    if caller is None:
        return _response(401, {"error": "unauthorized"})
    try:
        request = AskRequest.model_validate_json(event["body"] or "")
    except ValidationError:
        return _response(400, {"error": "invalid request"})
    try:
        result = answer(caller, request)
    except Exception as exc:
        logger.error("ask failed", extra={"error": type(exc).__name__})
        return _response(500, {"error": "internal error"})
    logger.info(
        "done", extra={"conversation_id": result["conversation_id"], "role": caller.role, "status": result["status"]}
    )
    return _response(200, result)


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status_code, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}
