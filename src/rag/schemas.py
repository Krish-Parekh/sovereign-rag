from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, computed_field
from ulid import ULID

TURN_TTL = timedelta(days=30)

type Role = Literal["user", "assistant"]
type Status = Literal["complete", "blocked"]
type UserRole = Literal["customer", "staff"]
type Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
type ConversationId = Annotated[str, StringConstraints(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")]


def new_id() -> str:
    return str(ULID())


def now() -> datetime:
    return datetime.now(UTC)


def conversation_pk(user_sub: str, conversation_id: str) -> str:
    return f"USER#{user_sub}#CONV#{conversation_id}"


class AskRequest(BaseModel):
    conversation_id: ConversationId | None = None
    question: Question


class Caller(BaseModel):
    sub: str
    role: UserRole


class Hit(BaseModel):
    score: float
    article_id: str
    url: str
    article_type: str
    text: str


class Turn(BaseModel):
    user_sub: str
    conversation_id: str
    turn_id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=now)
    role: Role
    content: str
    status: Status = "complete"

    @computed_field
    @property
    def pk(self) -> str:
        return conversation_pk(self.user_sub, self.conversation_id)

    @computed_field
    @property
    def sk(self) -> str:
        stamp = self.created_at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return f"MSG#{stamp}#{self.turn_id}"

    @computed_field
    @property
    def expires_at(self) -> int:
        return int((self.created_at + TURN_TTL).timestamp())
