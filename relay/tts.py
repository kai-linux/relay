"""Text-to-speech providers."""

from abc import ABC, abstractmethod

import openai


class TTSProvider(ABC):
    """Base class for text-to-speech providers.

    Subclass this to add new TTS backends (e.g. ElevenLabs, Google Cloud TTS,
    local Piper).
    """

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Convert text to audio bytes (mp3)."""
        ...


class OpenAITTS(TTSProvider):
    """OpenAI TTS API for text-to-speech."""

    def __init__(self, api_key: str, model: str = "tts-1", voice: str = "nova"):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model
        self.voice = voice

    async def synthesize(self, text: str) -> bytes:
        response = await self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format="mp3",
        )
        return response.content
