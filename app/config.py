from functools import lru_cache
from typing import Any

import orjson
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_group_id: int = Field(alias="ADMIN_GROUP_ID")
    admin_forum_topic_id: int = Field(alias="ADMIN_FORUM_TOPIC_ID")
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")
    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    wb_stores_json: str = Field(alias="WB_STORES_JSON")
    pdf_output_dir: str = Field(alias="PDF_OUTPUT_DIR")
    media_output_dir: str = Field(alias="MEDIA_OUTPUT_DIR")
    secret_key: str = Field(alias="SECRET_KEY")

    @property
    def wb_stores(self) -> list[dict[str, Any]]:
        return orjson.loads(self.wb_stores_json)


@lru_cache
def get_settings() -> Settings:
    return Settings()
