from rag.bedrock import chat_client
from rag.config import get_settings
from rag.deps import build_deps


def test_chat_client_targets_sydney_runtime() -> None:
    client = chat_client(get_settings())

    assert str(client.base_url) == "https://bedrock-runtime.ap-southeast-2.amazonaws.com/openai/v1/"
    assert client.aws_region == "ap-southeast-2"


def test_build_deps_pins_every_client_to_sydney() -> None:
    deps = build_deps(get_settings())

    assert deps.knowledge.meta.region_name == "ap-southeast-2"
    assert deps.table.name == "chat"
    assert deps.table.meta.client.meta.region_name == "ap-southeast-2"
