from datetime import UTC, datetime, timedelta
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field
from pydantic.alias_generators import to_camel
from ulid import ULID

TURN_TTL = timedelta(days=30)

type Role = Literal["user", "assistant"]
type Status = Literal["complete", "incomplete"]
type IngestionStatus = Literal["STARTING", "IN_PROGRESS", "COMPLETE", "FAILED", "STOPPING", "STOPPED"]
type Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
type ConversationId = Annotated[str, StringConstraints(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")]


def new_id() -> str:
    return str(ULID())


def now() -> datetime:
    return datetime.now(UTC)


def conversation_pk(user_sub: str, conversation_id: str) -> str:
    return f"USER#{user_sub}#CONV#{conversation_id}"


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, validate_by_name=True, validate_by_alias=True, serialize_by_alias=True
    )


class Caller(BaseModel):
    sub: str = Field(min_length=1)


class AskRequest(BaseModel):
    conversation_id: ConversationId | None = None
    question: Question


class Hit(BaseModel):
    key: str
    score: float
    article_id: str
    url: str
    text: str


class Retrieved(BaseModel):
    key: str
    score: float


class Turn(BaseModel):
    user_sub: str
    conversation_id: str
    turn_id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=now)
    role: Role
    content: str
    citations: list[str] = []
    retrieved: list[Retrieved] = []
    model: str | None = None
    ttft_ms: int | None = None
    total_ms: int | None = None
    tokens_out: int | None = None
    request_id: str
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


class Source(BaseModel):
    n: int
    url: str
    article_id: str
    score: float


class MetaEvent(BaseModel):
    name: ClassVar[str] = "meta"
    conversation_id: str
    request_id: str


class SourcesEvent(BaseModel):
    name: ClassVar[str] = "sources"
    sources: list[Source]


class TokenEvent(BaseModel):
    name: ClassVar[str] = "token"
    text: str


class DoneEvent(BaseModel):
    name: ClassVar[str] = "done"
    status: Status
    citations: list[str]
    ttft_ms: int | None
    total_ms: int
    tokens_out: int | None


type SseEvent = MetaEvent | SourcesEvent | TokenEvent | DoneEvent


class Article(BaseModel):
    id: str
    url: str
    contents: str


class StringValue(CamelModel):
    type: Literal["STRING"] = "STRING"
    string_value: str


class MetadataAttribute(CamelModel):
    value: StringValue
    include_for_embedding: bool = False


class CorpusAttributes(BaseModel):
    article_id: MetadataAttribute
    url: MetadataAttribute


class CorpusMetadata(CamelModel):
    metadata_attributes: CorpusAttributes

    @classmethod
    def for_article(cls, article: Article) -> "CorpusMetadata":
        return cls(
            metadata_attributes=CorpusAttributes(
                article_id=MetadataAttribute(value=StringValue(string_value=article.id)),
                url=MetadataAttribute(value=StringValue(string_value=article.url)),
            )
        )


class IngestionStatistics(CamelModel):
    number_of_documents_scanned: int = 0
    number_of_metadata_documents_scanned: int = 0
    number_of_new_documents_indexed: int = 0
    number_of_modified_documents_indexed: int = 0
    number_of_documents_deleted: int = 0
    number_of_documents_failed: int = 0


class IngestionJob(CamelModel):
    ingestion_job_id: str
    status: IngestionStatus
    statistics: IngestionStatistics = Field(default_factory=IngestionStatistics)
    failure_reasons: list[str] = []

    @property
    def finished(self) -> bool:
        return self.status in {"COMPLETE", "FAILED", "STOPPED"}

    @property
    def succeeded(self) -> bool:
        return self.status == "COMPLETE" and self.statistics.number_of_documents_failed == 0
