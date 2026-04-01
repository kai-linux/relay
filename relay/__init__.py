"""relay — voice bridge to CLI AI agents."""

__version__ = "0.1.0"

from .core import Relay, RelayResponse, RelayEvent
from .stt import STTProvider, WhisperSTT
from .tts import TTSProvider, OpenAITTS
from .agent import AgentBackend, AgentError, AgentEvent, ClaudeCodeAgent, CodexAgent, FallbackAgent
from .config import Config

__all__ = [
    "Relay",
    "RelayResponse",
    "STTProvider",
    "WhisperSTT",
    "TTSProvider",
    "OpenAITTS",
    "AgentBackend",
    "AgentError",
    "AgentEvent",
    "RelayEvent",
    "ClaudeCodeAgent",
    "CodexAgent",
    "FallbackAgent",
    "Config",
]
