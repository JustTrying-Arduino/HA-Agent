"""Configuration loaded from environment variables (set by run.sh from HA options)."""

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1"
    groq_api_key: str = ""
    brave_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: list[int] = field(default_factory=list)
    session_timeout_hours: int = 48
    max_session_messages: int = 15
    log_level: str = "info"
    supervisor_token: str = ""
    workspace_path: str = "/share/myagent/workspace"
    db_path: str = "/share/myagent/agent.db"
    ingress_port: int = 8099

    @classmethod
    def from_env(cls) -> "Config":
        chat_ids_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
        chat_ids = []
        if chat_ids_raw.strip():
            chat_ids = [int(x.strip()) for x in chat_ids_raw.split(",") if x.strip()]

        return cls(
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_api_base=os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4.1"),
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            brave_api_key=os.environ.get("BRAVE_API_KEY", ""),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_allowed_chat_ids=chat_ids,
            session_timeout_hours=int(os.environ.get("SESSION_TIMEOUT_HOURS", "48")),
            max_session_messages=int(os.environ.get("MAX_SESSION_MESSAGES", "15")),
            log_level=os.environ.get("LOG_LEVEL", "info"),
            supervisor_token=os.environ.get("SUPERVISOR_TOKEN", ""),
        )


cfg = Config.from_env()
