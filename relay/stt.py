"""Speech-to-text providers."""

from abc import ABC, abstractmethod

import openai


class STTProvider(ABC):
    """Base class for speech-to-text providers.

    Subclass this to add new STT backends (e.g. local Whisper, Deepgram,
    Google Cloud Speech).
    """

    @abstractmethod
    async def transcribe(self, audio_data: bytes, mime_type: str = "audio/webm") -> str:
        """Transcribe audio bytes to text."""
        ...


class WhisperSTT(STTProvider):
    """OpenAI Whisper API for speech-to-text."""

    def __init__(self, api_key: str, model: str = "whisper-1"):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model

    async def transcribe(self, audio_data: bytes, mime_type: str = "audio/webm") -> str:
        ext = mime_type.split("/")[-1].split(";")[0]
        if ext == "mpeg":
            ext = "mp3"
        transcript = await self.client.audio.transcriptions.create(
            model=self.model,
            file=(f"audio.{ext}", audio_data),
        )
        return transcript.text
