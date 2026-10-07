from dataclasses import dataclass

import boto3
from openai import AsyncOpenAI
from types_boto3_bedrock_agent_runtime import AgentsforBedrockRuntimeClient
from types_boto3_dynamodb.service_resource import Table

from rag.bedrock import chat_client
from rag.config import Settings


@dataclass(frozen=True)
class Deps:
    settings: Settings
    chat: AsyncOpenAI
    knowledge: AgentsforBedrockRuntimeClient
    table: Table


def build_deps(settings: Settings) -> Deps:
    session = boto3.session.Session(region_name=settings.region)
    return Deps(
        settings=settings,
        chat=chat_client(settings),
        knowledge=session.client("bedrock-agent-runtime"),
        table=session.resource("dynamodb").Table(settings.chat_table),
    )
