from datetime import UTC, datetime

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

from rag.corpus import CorpusRow, select_articles, start_ingestion, upload, wait_for_ingestion
from rag.schemas import Article, CorpusMetadata

STAMP = datetime(2026, 10, 7, tzinfo=UTC)


def _rows(n: int) -> list[CorpusRow]:
    kinds = ["article", "feature_request", "known_issue"]
    return [
        CorpusRow(id=f"id{i:03}", url=f"https://wix.com/{i}", contents=f"text {i}", article_type=kinds[i % 3])
        for i in range(n)
    ]


def _job(status: str, failed: int = 0) -> dict[str, object]:
    return {
        "ingestionJob": {
            "knowledgeBaseId": "KB",
            "dataSourceId": "DS",
            "ingestionJobId": "J1",
            "status": status,
            "statistics": {"numberOfDocumentsScanned": 400, "numberOfDocumentsFailed": failed},
            "startedAt": STAMP,
            "updatedAt": STAMP,
        }
    }


def test_selection_is_deterministic_for_a_seed() -> None:
    rows = _rows(300)

    assert select_articles(rows, 40, 42) == select_articles(list(reversed(rows)), 40, 42)
    assert select_articles(rows, 40, 42) != select_articles(rows, 40, 7)


def test_only_help_articles_are_selected() -> None:
    selected = select_articles(_rows(300), 40, 42)

    assert len(selected) == 40
    assert all(int(a.id[2:]) % 3 == 0 for a in selected)


def test_count_is_capped_by_available_articles() -> None:
    assert len(select_articles(_rows(9), 400, 42)) == 3


@mock_aws
def test_upload_writes_markdown_and_metadata_per_article() -> None:
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="docs", CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"})
    article = Article(id="a1", url="https://wix.com/1", contents="# Title\nBody")

    upload(s3, "docs", [article])
    upload(s3, "docs", [article])

    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="docs")["Contents"]]
    assert sorted(keys) == ["corpus/a1.md", "corpus/a1.md.metadata.json"]
    assert s3.get_object(Bucket="docs", Key="corpus/a1.md")["Body"].read() == b"# Title\nBody"
    metadata = s3.get_object(Bucket="docs", Key="corpus/a1.md.metadata.json")["Body"].read()
    assert CorpusMetadata.model_validate_json(metadata) == CorpusMetadata.for_article(article)


def test_start_ingestion_returns_job_id() -> None:
    agent = boto3.client("bedrock-agent")
    with Stubber(agent) as stub:
        stub.add_response("start_ingestion_job", _job("STARTING"), {"knowledgeBaseId": "KB", "dataSourceId": "DS"})

        assert start_ingestion(agent, "KB", "DS") == "J1"


def test_wait_polls_until_the_job_finishes() -> None:
    agent = boto3.client("bedrock-agent")
    sleeps: list[float] = []
    params = {"knowledgeBaseId": "KB", "dataSourceId": "DS", "ingestionJobId": "J1"}
    with Stubber(agent) as stub:
        stub.add_response("get_ingestion_job", _job("IN_PROGRESS"), params)
        stub.add_response("get_ingestion_job", _job("COMPLETE"), params)

        job = wait_for_ingestion(agent, "KB", "DS", "J1", poll_s=10, sleep=sleeps.append)

    assert job.succeeded
    assert sleeps == [10]


def test_job_with_failed_documents_is_not_a_success() -> None:
    agent = boto3.client("bedrock-agent")
    with Stubber(agent) as stub:
        stub.add_response("get_ingestion_job", _job("COMPLETE", failed=2))

        job = wait_for_ingestion(agent, "KB", "DS", "J1", poll_s=10, sleep=lambda _: None)

    assert job.finished
    assert not job.succeeded


@pytest.mark.parametrize("status", ["FAILED", "STOPPED"])
def test_failed_or_stopped_job_is_not_a_success(status: str) -> None:
    agent = boto3.client("bedrock-agent")
    with Stubber(agent) as stub:
        stub.add_response("get_ingestion_job", _job(status))

        assert not wait_for_ingestion(agent, "KB", "DS", "J1", poll_s=10, sleep=lambda _: None).succeeded
