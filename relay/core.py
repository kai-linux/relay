"""Core relay pipeline: audio in -> STT -> agent -> TTS -> audio out.

This module contains the provider-agnostic orchestration logic. It can be
used standalone (embedded in another app) or served over HTTP via relay.app.
"""

from dataclasses import dataclass

from .agent import AgentBackend
from .stt import STTProvider
from .tts import TTSProvider


@dataclass
class RelayResponse:
    """Result of a single relay round-trip."""

    transcript: str  # what the user said (STT output)
    text: str  # what the agent replied
    audio: bytes  # spoken agent reply (TTS output, mp3)


class Relay:
    """Orchestrates the voice relay pipeline.

    Usage::

        relay = Relay(stt=WhisperSTT(...), tts=OpenAITTS(...), agent=ClaudeCodeAgent(...))
        response = await relay.process(audio_bytes, session_id="abc")
        # response.transcript, response.text, response.audio
    """

    def __init__(
        self, stt: STTProvider, tts: TTSProvider, agent: AgentBackend
    ) -> None:
        self.stt = stt
        self.tts = tts
        self.agent = agent

    async def process(
        self,
        audio_data: bytes,
        session_id: str,
        mime_type: str = "audio/webm",
    ) -> RelayResponse:
        """Run the full pipeline: transcribe -> agent -> synthesize."""
        transcript = await self.stt.transcribe(audio_data, mime_type)

        if not transcript.strip():
            return RelayResponse(
                transcript="",
                text="I didn't catch that. Could you try again?",
                audio=await self.tts.synthesize(
                    "I didn't catch that. Could you try again?"
                ),
            )

        response_text = await self.agent.send(transcript, session_id)
        audio_out = await self.tts.synthesize(response_text)

        return RelayResponse(
            transcript=transcript, text=response_text, audio=audio_out
        )
