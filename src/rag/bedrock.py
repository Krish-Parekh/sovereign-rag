from openai import AsyncBedrockOpenAI

from rag.config import Settings

CHAT_TIMEOUT_S = 240.0


def chat_client(settings: Settings) -> AsyncBedrockOpenAI:
    return AsyncBedrockOpenAI(aws_region=settings.region, base_url=settings.chat_base_url, timeout=CHAT_TIMEOUT_S)
