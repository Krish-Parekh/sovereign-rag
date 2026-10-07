from pydantic import BaseModel, ConfigDict, Field
from types_boto3_bedrock_agent_runtime import AgentsforBedrockRuntimeClient

from rag.schemas import Hit

TOP_K = 5


class ResultContent(BaseModel):
    text: str


class ResultMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    article_id: str
    url: str
    chunk_id: str | None = Field(default=None, alias="x-amz-bedrock-kb-chunk-id")


class RetrievalResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: ResultContent
    score: float
    metadata: ResultMetadata
    document_id: str | None = Field(default=None, alias="documentId")

    def hit(self) -> Hit:
        return Hit(
            key=self.metadata.chunk_id or self.document_id or self.metadata.article_id,
            score=self.score,
            article_id=self.metadata.article_id,
            url=self.metadata.url,
            text=self.content.text,
        )


def retrieve(client: AgentsforBedrockRuntimeClient, knowledge_base_id: str, query: str) -> list[Hit]:
    response = client.retrieve(
        knowledgeBaseId=knowledge_base_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": TOP_K}},
    )
    return [RetrievalResult.model_validate(result).hit() for result in response["retrievalResults"]]


def top_score(hits: list[Hit]) -> float:
    return max(hit.score for hit in hits)
