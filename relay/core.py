"""Core relay pipeline: audio in -> STT -> agent -> TTS -> audio out.

This module contains the provider-agnostic orchestration logic. It can be
used standalone (embedded in another app) or served over HTTP via relay.app.
"""

import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from .agent import AgentBackend
from .stt import STTProvider
from .tts import TTSProvider

log = logging.getLogger(__name__)


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

        Agent events and TTS synthesis run concurrently via an asyncio.Queue
        so that TTS latency never blocks reading the next agent event.
        """
        yield RelayEvent(event="status", text="Let me listen to that...")

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
        yield RelayEvent(event="status", text="On it, give me a moment...")

        # Queue bridges the agent stream reader and the event yielder.
        # None sentinel signals all work (agent + TTS) is done.
        queue: asyncio.Queue[RelayEvent | None] = asyncio.Queue()
        response_text = ""
        tts_tasks: list[asyncio.Task] = []

        async def _synthesize_status(text: str):
            """TTS a short status clip and push to queue."""
            try:
                clip = await self.tts.synthesize(text)
                await queue.put(RelayEvent(
                    event="status_audio",
                    text=text,
                    audio_base64=base64.b64encode(clip).decode(),
                ))
            except Exception:
                pass  # non-critical

        async def _read_agent_and_synthesize():
            """Read agent events and fire off TTS for status updates."""
            nonlocal response_text
            try:
                async for agent_event in self.agent.send_stream(
                    transcript, session_id
                ):
                    if agent_event.type == "status":
                        # Push text status immediately (no blocking)
                        await queue.put(
                            RelayEvent(event="status", text=agent_event.text)
                        )
                        # Synthesize audio in a background task so we don't
                        # block reading the next agent event
                        task = asyncio.create_task(
                            _synthesize_status(agent_event.text)
                        )
                        tts_tasks.append(task)
                    elif agent_event.type == "result":
                        response_text = agent_event.text
            except Exception as e:
                log.error("Agent stream error: %s", e)
                await queue.put(
                    RelayEvent(event="error", text=str(e))
                )

            # Wait for all pending TTS tasks before signalling done
            if tts_tasks:
                await asyncio.gather(*tts_tasks, return_exceptions=True)
            await queue.put(None)

        # Synthesize the initial status immediately so the user hears
        # something right away, before the CLI even starts up.
        initial_tts = asyncio.create_task(
            _synthesize_status("On it, give me a moment...")
        )
        tts_tasks.append(initial_tts)

        # Start the agent reader — it runs concurrently while we yield
        agent_task = asyncio.create_task(_read_agent_and_synthesize())

        # Yield events as they arrive from the queue.
        # Send a heartbeat every 15s to keep the connection alive on
        # mobile browsers that close idle streams.
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield RelayEvent(event="status", text="Still working on it...")
                continue
            if event is None:
                break
            yield event

        # Make sure the agent task is fully done
        await agent_task

        yield RelayEvent(event="response", text=response_text)
        yield RelayEvent(event="status", text="Let me put that into words...")

        async for chunk in self.tts.synthesize_stream(response_text):
            yield RelayEvent(
                event="audio",
                audio_base64=base64.b64encode(chunk).decode(),
                session_id=session_id,
            )
