"""Configuration management."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # OpenAI API (used for Whisper STT and TTS)
    openai_api_key: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )

    # Speech-to-text
    stt_model: str = field(
        default_factory=lambda: os.environ.get("RELAY_STT_MODEL", "whisper-1")
    )

    # Text-to-speech
    tts_model: str = field(
        default_factory=lambda: os.environ.get("RELAY_TTS_MODEL", "tts-1")
    )
    tts_voice: str = field(
        default_factory=lambda: os.environ.get("RELAY_TTS_VOICE", "nova")
    )

    # Agent backend
    agent_backend: str = field(
        default_factory=lambda: os.environ.get("RELAY_AGENT_BACKEND", "claude-code")
    )
    work_dir: str = field(
        default_factory=lambda: os.environ.get("RELAY_WORK_DIR", os.getcwd())
    )
    agent_timeout: int = field(
        default_factory=lambda: int(os.environ.get("RELAY_AGENT_TIMEOUT", "300"))
    )

    # Server
    host: str = field(
        default_factory=lambda: os.environ.get("RELAY_HOST", "0.0.0.0")
    )
    port: int = field(
        default_factory=lambda: int(os.environ.get("RELAY_PORT", "5000"))
    )
    secret_key: str = field(
        default_factory=lambda: os.environ.get(
            "RELAY_SECRET_KEY", "dev-secret-change-me"
        )
    )

    def validate(self):
        if not self.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is required. Set it in .env or as an environment variable."
            )
