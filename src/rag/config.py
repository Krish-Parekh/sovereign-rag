from functools import cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    region: str = "ap-southeast-2"
    chat_model: str = "qwen.qwen3-32b-v1:0"
    knowledge_base_id: str
    chat_table: str
    answer_timeout_s: float = 270.0

    @property
    def chat_base_url(self) -> str:
        return f"https://bedrock-runtime.{self.region}.amazonaws.com/openai/v1"


@cache
def get_settings() -> Settings:
    return Settings.model_validate({})
