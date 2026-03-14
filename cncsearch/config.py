"""Configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


@dataclass
class Config:
    database_path: str
    embedding_provider: str  # "jina" | "local"
    jina_api_key: str | None
    web_secret_key: str
    web_initial_password: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        provider = os.environ.get("EMBEDDING_PROVIDER", "jina")
        jina_key = os.environ.get("JINA_API_KEY")

        if provider == "jina" and not jina_key:
            raise ValueError("JINA_API_KEY is required when EMBEDDING_PROVIDER=jina")

        secret_key = os.environ.get("WEB_SECRET_KEY", "")
        if not secret_key:
            raise ValueError(
                "WEB_SECRET_KEY must be set to a secure random string. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

        initial_password = os.environ.get("WEB_INITIAL_PASSWORD", "admin")
        if initial_password == "admin":
            logger.warning(
                "WEB_INITIAL_PASSWORD is set to the default 'admin'. "
                "Change it in your .env file to a secure password."
            )

        return cls(
            database_path=os.environ.get("DATABASE_PATH", "./data/cncsearch.db"),
            embedding_provider=provider,
            jina_api_key=jina_key,
            web_secret_key=secret_key,
            web_initial_password=initial_password,
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
