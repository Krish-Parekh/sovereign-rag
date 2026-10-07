import logging
import random
import time
from collections.abc import Callable

import httpx
from pydantic import BaseModel
from types_boto3_bedrock_agent import AgentsforBedrockClient
from types_boto3_s3 import S3Client

from rag.schemas import Article, CorpusMetadata, IngestionJob

CORPUS_URL = (
    "https://huggingface.co/datasets/Wix/WixQA/resolve/d662dc42479c14e202eccd832f8c4b66a035c4cc"
    "/wix_kb_corpus/wix_kb_corpus.jsonl"
)
POLL_S = 10.0

log = logging.getLogger("corpus")


class CorpusRow(BaseModel):
    id: str
    url: str
    contents: str
    article_type: str


def load_rows(url: str = CORPUS_URL) -> list[CorpusRow]:
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        return [CorpusRow.model_validate_json(line) for line in response.iter_lines() if line.strip()]


def select_articles(rows: list[CorpusRow], count: int, seed: int) -> list[Article]:
    articles = sorted(
        (Article(id=row.id, url=row.url, contents=row.contents) for row in rows if row.article_type == "article"),
        key=lambda article: article.id,
    )
    return random.Random(seed).sample(articles, min(count, len(articles)))


def upload(s3: S3Client, bucket: str, articles: list[Article]) -> None:
    for article in articles:
        key = f"corpus/{article.id}.md"
        s3.put_object(Bucket=bucket, Key=key, Body=article.contents.encode(), ContentType="text/markdown")
        s3.put_object(
            Bucket=bucket,
            Key=f"{key}.metadata.json",
            Body=CorpusMetadata.for_article(article).model_dump_json().encode(),
            ContentType="application/json",
        )


def start_ingestion(agent: AgentsforBedrockClient, knowledge_base_id: str, data_source_id: str) -> str:
    response = agent.start_ingestion_job(knowledgeBaseId=knowledge_base_id, dataSourceId=data_source_id)
    return response["ingestionJob"]["ingestionJobId"]


def wait_for_ingestion(
    agent: AgentsforBedrockClient,
    knowledge_base_id: str,
    data_source_id: str,
    job_id: str,
    poll_s: float = POLL_S,
    sleep: Callable[[float], None] = time.sleep,
) -> IngestionJob:
    while True:
        response = agent.get_ingestion_job(
            knowledgeBaseId=knowledge_base_id, dataSourceId=data_source_id, ingestionJobId=job_id
        )
        job = IngestionJob.model_validate(response["ingestionJob"])
        log.info("ingestion %s %s", job.status, job.statistics.model_dump_json())
        if job.finished:
            return job
        sleep(poll_s)
