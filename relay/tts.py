"""Text-to-speech providers."""

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import openai


# Split on sentence-ending punctuation followed by whitespace, keeping the
# punctuation with the preceding sentence.  Handles ". ", "! ", "? ", and
# also ".\n" etc.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class TTSProvider(ABC):
    """Base class for text-to-speech providers.

    Subclass this to add new TTS backends (e.g. ElevenLabs, Google Cloud TTS,
    local Piper).
    """

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Convert text to audio bytes (mp3)."""
        ...

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield audio chunks for progressive playback.

        Default splits text into sentences and synthesizes each individually.
        Override for providers with native streaming support.
        """
        sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
        if not sentences:
            yield await self.synthesize(text)
            return
        # Short responses (single sentence) — just return the whole thing
        if len(sentences) == 1:
            yield await self.synthesize(text)
            return
        for sentence in sentences:
            yield await self.synthesize(sentence)


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
