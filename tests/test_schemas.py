import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from rag.config import get_settings
from rag.schemas import Article, AskRequest, CorpusMetadata, IngestionJob, Turn


def test_settings_point_chat_at_sydney_runtime() -> None:
    settings = get_settings()

    assert settings.region == "ap-southeast-2"
    assert settings.chat_model == "qwen.qwen3-32b-v1:0"
    assert settings.chat_base_url == "https://bedrock-runtime.ap-southeast-2.amazonaws.com/openai/v1"
    assert settings.otel_exporter_otlp_traces_endpoint is None


def test_ask_request_strips_question() -> None:
    assert AskRequest(question="  how do I add a domain?  ").question == "how do I add a domain?"


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_ask_request_rejects_blank_or_oversized_question(question: str) -> None:
    with pytest.raises(ValidationError):
        AskRequest(question=question)


def test_ask_request_rejects_malformed_conversation_id() -> None:
    with pytest.raises(ValidationError):
        AskRequest(conversation_id="USER#other", question="hi")


def test_turn_keys_are_partitioned_by_user_and_sort_chronologically() -> None:
    start = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
    first = Turn(user_sub="sub-a", conversation_id="c1", role="user", content="q", request_id="r", created_at=start)
    second = Turn(
        user_sub="sub-a",
        conversation_id="c1",
        role="assistant",
        content="a",
        request_id="r",
        created_at=start + timedelta(milliseconds=5),
    )

    assert first.pk == second.pk == "USER#sub-a#CONV#c1"
    assert first.sk.startswith("MSG#2026-10-07T09:00:00.000Z#")
    assert first.sk < second.sk


def test_turn_expires_thirty_days_after_creation() -> None:
    created = datetime(2026, 10, 7, tzinfo=UTC)
    turn = Turn(user_sub="s", conversation_id="c1", role="user", content="q", request_id="r", created_at=created)

    assert turn.expires_at == int((created + timedelta(days=30)).timestamp())


def test_corpus_metadata_matches_knowledge_base_format() -> None:
    article = Article(id="a1", url="https://support.wix.com/a1", contents="text")

    assert json.loads(CorpusMetadata.for_article(article).model_dump_json()) == {
        "metadataAttributes": {
            "article_id": {"value": {"type": "STRING", "stringValue": "a1"}, "includeForEmbedding": False},
            "url": {
                "value": {"type": "STRING", "stringValue": "https://support.wix.com/a1"},
                "includeForEmbedding": False,
            },
        }
    }


def test_ingestion_job_reads_api_shape() -> None:
    job = IngestionJob.model_validate(
        {
            "ingestionJobId": "J1",
            "status": "COMPLETE",
            "statistics": {"numberOfDocumentsScanned": 400, "numberOfDocumentsFailed": 0},
            "knowledgeBaseId": "KB",
        }
    )

    assert job.finished
    assert job.succeeded
    assert job.statistics.number_of_documents_scanned == 400
