from pydantic import BaseModel, Field, ValidationError

from rag.schemas import Caller, new_id


class Claims(BaseModel):
    sub: str = Field(min_length=1)


class Authorizer(BaseModel):
    claims: Claims


class RequestContext(BaseModel):
    authorizer: Authorizer


class LambdaContextHeader(BaseModel):
    request_id: str


def caller_from_context(header: str | None) -> Caller | None:
    if header is None:
        return None
    try:
        context = RequestContext.model_validate_json(header)
    except ValidationError:
        return None
    return Caller(sub=context.authorizer.claims.sub)


def request_id_from_context(header: str | None) -> str:
    if header is None:
        return new_id()
    return LambdaContextHeader.model_validate_json(header).request_id
