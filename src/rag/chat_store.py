import json
from decimal import Decimal

from boto3.dynamodb.conditions import Key
from types_boto3_dynamodb.service_resource import Table

from rag.schemas import Turn, conversation_pk


def save_turn(table: Table, turn: Turn) -> None:
    table.put_item(Item=json.loads(turn.model_dump_json(), parse_float=Decimal))


def load_history(table: Table, user_sub: str, conversation_id: str, limit: int) -> list[Turn]:
    response = table.query(
        KeyConditionExpression=Key("pk").eq(conversation_pk(user_sub, conversation_id)),
        ScanIndexForward=False,
        Limit=limit,
    )
    turns = [Turn.model_validate(item) for item in response.get("Items", [])]
    return [turn for turn in reversed(turns) if turn.status == "complete"]
