"""relay — voice bridge to CLI AI agents."""

__version__ = "0.1.0"

from .core import Relay, RelayResponse
from .stt import STTProvider, WhisperSTT
from .tts import TTSProvider, OpenAITTS
from .agent import AgentBackend, ClaudeCodeAgent
from .config import Config

__all__ = [
    "Relay",
    "RelayResponse",
    "STTProvider",
    "WhisperSTT",
    "TTSProvider",
    "OpenAITTS",
    "AgentBackend",
    "ClaudeCodeAgent",
    "Config",
]
