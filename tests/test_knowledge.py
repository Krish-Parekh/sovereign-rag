import boto3
import pytest
from botocore.stub import Stubber
from pydantic import ValidationError

from rag.knowledge import retrieve, top_score

PARAMS = {
    "knowledgeBaseId": "KB12345678",
    "retrievalQuery": {"text": "connect a domain"},
    "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 5}},
}


def _result(n: int, chunk_id: str | None = None) -> dict[str, object]:
    metadata: dict[str, object] = {"article_id": f"a{n}", "url": f"https://support.wix.com/a{n}"}
    if chunk_id is not None:
        metadata["x-amz-bedrock-kb-chunk-id"] = chunk_id
    return {
        "content": {"text": f"text {n}", "type": "TEXT"},
        "location": {"type": "S3", "s3Location": {"uri": f"s3://docs/corpus/a{n}.md"}},
        "metadata": metadata,
        "score": 0.9 - 0.1 * n,
        "documentId": f"doc-{n}",
    }


def test_retrieve_maps_results_to_hits() -> None:
    client = boto3.client("bedrock-agent-runtime")
    with Stubber(client) as stub:
        stub.add_response("retrieve", {"retrievalResults": [_result(1, "chunk-1"), _result(2, "chunk-2")]}, PARAMS)

        hits = retrieve(client, "KB12345678", "connect a domain")

    assert [(h.key, h.article_id, h.url, h.text) for h in hits] == [
        ("chunk-1", "a1", "https://support.wix.com/a1", "text 1"),
        ("chunk-2", "a2", "https://support.wix.com/a2", "text 2"),
    ]
    assert top_score(hits) == pytest.approx(0.8)


def test_key_falls_back_to_document_id() -> None:
    client = boto3.client("bedrock-agent-runtime")
    with Stubber(client) as stub:
        stub.add_response("retrieve", {"retrievalResults": [_result(1)]}, PARAMS)

        assert retrieve(client, "KB12345678", "connect a domain")[0].key == "doc-1"


def test_no_results_is_an_empty_list() -> None:
    client = boto3.client("bedrock-agent-runtime")
    with Stubber(client) as stub:
        stub.add_response("retrieve", {"retrievalResults": []}, PARAMS)

        assert retrieve(client, "KB12345678", "connect a domain") == []


def test_result_without_url_metadata_is_rejected() -> None:
    client = boto3.client("bedrock-agent-runtime")
    broken = _result(1)
    broken["metadata"] = {"article_id": "a1"}
    with Stubber(client) as stub:
        stub.add_response("retrieve", {"retrievalResults": [broken]}, PARAMS)

        with pytest.raises(ValidationError):
            retrieve(client, "KB12345678", "connect a domain")
