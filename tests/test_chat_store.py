from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws
from types_boto3_dynamodb.service_resource import Table

from rag.chat_store import load_history, save_turn
from rag.schemas import Retrieved, Turn

START = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


@pytest.fixture
def table() -> Iterator[Table]:
    with mock_aws():
        yield boto3.resource("dynamodb").create_table(
            TableName="chat",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )


def _turn(i: int, user_sub: str = "sub-a", conversation_id: str = "c1", **fields: str) -> Turn:
    return Turn.model_validate(
        {
            "user_sub": user_sub,
            "conversation_id": conversation_id,
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"turn {i}",
            "request_id": "r",
            "created_at": START + timedelta(seconds=i),
            **fields,
        }
    )


def test_saved_turn_round_trips_with_floats(table: Table) -> None:
    turn = _turn(1).model_copy(
        update={
            "retrieved": [Retrieved(key="chunk-1", score=0.123)],
            "citations": ["https://support.wix.com/a1"],
            "ttft_ms": 900,
            "tokens_out": 42,
            "model": "qwen.qwen3-32b-v1:0",
        }
    )

    save_turn(table, turn)

    assert load_history(table, "sub-a", "c1", 6) == [turn]


def test_history_returns_last_messages_oldest_first(table: Table) -> None:
    for i in range(9):
        save_turn(table, _turn(i))
    save_turn(table, _turn(0, conversation_id="other"))

    history = load_history(table, "sub-a", "c1", 6)

    assert [t.content for t in history] == [f"turn {i}" for i in range(3, 9)]


def test_history_skips_incomplete_turns(table: Table) -> None:
    save_turn(table, _turn(0))
    save_turn(table, _turn(1, status="incomplete"))

    assert [t.content for t in load_history(table, "sub-a", "c1", 6)] == ["turn 0"]


def test_other_users_conversation_is_invisible(table: Table) -> None:
    save_turn(table, _turn(0, user_sub="sub-a"))

    assert load_history(table, "sub-b", "c1", 6) == []


def test_saved_item_has_user_partition_and_ttl(table: Table) -> None:
    turn = _turn(0)
    save_turn(table, turn)

    item = table.get_item(Key={"pk": "USER#sub-a#CONV#c1", "sk": turn.sk}).get("Item")

    assert item is not None
    assert item["expires_at"] == int((START + timedelta(days=30)).timestamp())
