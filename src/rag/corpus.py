import json
import logging
import random
import time

import httpx
from pydantic import BaseModel
from types_boto3_bedrock_agent import AgentsforBedrockClient
from types_boto3_bedrock_agent.type_defs import IngestionJobTypeDef
from types_boto3_s3 import S3Client

CORPUS_URL = (
    "https://huggingface.co/datasets/Wix/WixQA/resolve/d662dc42479c14e202eccd832f8c4b66a035c4cc"
    "/wix_kb_corpus/wix_kb_corpus.jsonl"
)
FINISHED = {"COMPLETE", "FAILED", "STOPPED"}
COUNTS = {"article": 400, "known_issue": 63, "feature_request": 100}

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


def select_articles(rows: list[CorpusRow], seed: int) -> list[CorpusRow]:
    selected: list[CorpusRow] = []
    for article_type, count in COUNTS.items():
        of_type = sorted((row for row in rows if row.article_type == article_type), key=lambda row: row.id)
        selected += random.Random(seed).sample(of_type, min(count, len(of_type)))
    return selected


def metadata_json(article: CorpusRow) -> str:
    def attribute(value: str) -> dict[str, object]:
        return {"value": {"type": "STRING", "stringValue": value}, "includeForEmbedding": False}

    return json.dumps(
        {
            "metadataAttributes": {
                "article_id": attribute(article.id),
                "url": attribute(article.url),
                "article_type": attribute(article.article_type),
            }
        }
    )


def upload(s3: S3Client, bucket: str, articles: list[CorpusRow]) -> None:
    for article in articles:
        key = f"corpus/{article.id}.md"
        s3.put_object(Bucket=bucket, Key=key, Body=article.contents.encode(), ContentType="text/markdown")
        s3.put_object(
            Bucket=bucket,
            Key=f"{key}.metadata.json",
            Body=metadata_json(article).encode(),
            ContentType="application/json",
        )


def start_ingestion(agent: AgentsforBedrockClient, knowledge_base_id: str, data_source_id: str) -> str:
    response = agent.start_ingestion_job(knowledgeBaseId=knowledge_base_id, dataSourceId=data_source_id)
    return response["ingestionJob"]["ingestionJobId"]


def wait_for_ingestion(
    agent: AgentsforBedrockClient, knowledge_base_id: str, data_source_id: str, job_id: str
) -> IngestionJobTypeDef:
    while True:
        job = agent.get_ingestion_job(
            knowledgeBaseId=knowledge_base_id, dataSourceId=data_source_id, ingestionJobId=job_id
        )["ingestionJob"]
        log.info("ingestion %s %s", job["status"], job.get("statistics"))
        if job["status"] in FINISHED:
            return job
        time.sleep(10)


def succeeded(job: IngestionJobTypeDef) -> bool:
    failed = job.get("statistics", {}).get("numberOfDocumentsFailed", 0)
    return job["status"] == "COMPLETE" and failed == 0
