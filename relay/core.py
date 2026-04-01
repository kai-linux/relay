"""Core relay pipeline: audio in -> STT -> agent -> TTS -> audio out.

This module contains the provider-agnostic orchestration logic. It can be
used standalone (embedded in another app) or served over HTTP via relay.app.
"""

import base64
from collections.abc import AsyncIterator
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


@dataclass
class RelayEvent:
    """A streaming event from the relay pipeline."""

    event: str  # "status", "transcript", "response", "audio", "error"
    text: str = ""
    audio_base64: str = ""
    session_id: str = ""


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

    async def process_stream(
        self,
        audio_data: bytes,
        session_id: str,
        mime_type: str = "audio/webm",
    ) -> AsyncIterator[RelayEvent]:
        """Stream events through the pipeline for real-time client updates.

        Status updates are synthesized to short audio clips so the user
        *hears* progress ("Reading files...", "Editing code...") instead
        of sitting in silence.
        """
        yield RelayEvent(event="status", text="Transcribing your voice...")

        transcript = await self.stt.transcribe(audio_data, mime_type)

        if not transcript.strip():
            fallback = "I didn't catch that. Could you try again?"
            yield RelayEvent(event="response", text=fallback)
            audio_out = await self.tts.synthesize(fallback)
            yield RelayEvent(
                event="audio",
                audio_base64=base64.b64encode(audio_out).decode(),
                session_id=session_id,
            )
            return

        yield RelayEvent(event="transcript", text=transcript)
        yield RelayEvent(event="status", text="Agent is working...")

        response_text = ""
        async for agent_event in self.agent.send_stream(transcript, session_id):
            if agent_event.type == "status":
                yield RelayEvent(event="status", text=agent_event.text)
                # Synthesize short status clip so the user hears progress
                try:
                    clip = await self.tts.synthesize(agent_event.text)
                    yield RelayEvent(
                        event="status_audio",
                        text=agent_event.text,
                        audio_base64=base64.b64encode(clip).decode(),
                    )
                except Exception:
                    pass  # non-critical — text status was already sent
            elif agent_event.type == "result":
                response_text = agent_event.text

        yield RelayEvent(event="response", text=response_text)
        yield RelayEvent(event="status", text="Generating speech...")

        audio_out = await self.tts.synthesize(response_text)
        yield RelayEvent(
            event="audio",
            audio_base64=base64.b64encode(audio_out).decode(),
            session_id=session_id,
        )
