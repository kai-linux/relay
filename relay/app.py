"""Quart web application — thin HTTP layer over the Relay core."""

import base64
import json
import uuid

from quart import Quart, jsonify, request, Response

from .agent import ClaudeCodeAgent, CodexAgent, FallbackAgent
from .config import Config
from .core import Relay
from .stt import WhisperSTT
from .tts import OpenAITTS

AGENT_REGISTRY = {
    "claude-code": ClaudeCodeAgent,
    "codex": CodexAgent,
}


def create_app(relay: Relay, config: Config | None = None) -> Quart:
    """Create the Quart app with a pre-configured Relay instance.

    Use this when you want full control over providers (e.g. embedding relay
    in another application with custom STT/TTS/agent backends).
    """
    config = config or Config()
    app = Quart(__name__, static_folder="static", static_url_path="/static")
    app.secret_key = config.secret_key

    @app.route("/")
    async def index():
        return await app.send_static_file("index.html")

    @app.route("/api/relay", methods=["POST"])
    async def relay_endpoint():
        """Voice relay: audio in -> transcribe -> agent -> TTS -> audio out.

        Streams newline-delimited JSON events for real-time progress updates.
        Falls back to single JSON response if client doesn't accept NDJSON.
        """
        files = await request.files
        audio_file = files.get("audio")
        if not audio_file:
            return jsonify({"error": "No audio file provided"}), 400

        form = await request.form
        session_id = form.get("session_id", str(uuid.uuid4()))
        audio_data = audio_file.read()
        mime_type = audio_file.content_type or "audio/webm"

        accept = request.headers.get("Accept", "")

        if "text/event-stream" in accept:
            return await _stream_response(relay, audio_data, session_id, mime_type)

        # Legacy non-streaming path
        result = await relay.process(audio_data, session_id, mime_type)

        return jsonify(
            {
                "transcript": result.transcript,
                "response": result.text,
                "audio_base64": base64.b64encode(result.audio).decode(),
                "session_id": session_id,
            }
        )

    async def _stream_response(relay, audio_data, session_id, mime_type):
        """Stream NDJSON events through the pipeline."""

        async def generate():
            try:
                async for event in relay.process_stream(
                    audio_data, session_id, mime_type
                ):
                    payload = {"event": event.event}
                    if event.text:
                        payload["text"] = event.text
                    if event.audio_base64:
                        payload["audio_base64"] = event.audio_base64
                    if event.session_id:
                        payload["session_id"] = event.session_id
                    yield json.dumps(payload) + "\n"
            except Exception as e:
                yield json.dumps({"event": "error", "text": str(e)}) + "\n"

        return Response(generate(), content_type="application/x-ndjson")

    @app.route("/api/health")
    async def health():
        return jsonify({"status": "ok"})

    return app


def _build_agent(config: Config):
    """Build agent from config. Supports comma-separated fallback chains.

    Examples:
        RELAY_AGENT_BACKEND=claude-code           -> single agent
        RELAY_AGENT_BACKEND=claude-code,codex      -> claude-code with codex fallback
    """
    names = [n.strip() for n in config.agent_backend.split(",")]
    agents = []
    for name in names:
        cls = AGENT_REGISTRY.get(name)
        if not cls:
            raise ValueError(
                f"Unknown agent backend '{name}'. "
                f"Choose from: {', '.join(AGENT_REGISTRY)}"
            )
        agents.append(cls(
            work_dir=config.work_dir,
            timeout=config.agent_timeout,
        ))

    if len(agents) == 1:
        return agents[0]
    return FallbackAgent(agents)


def create_app_from_config(config: Config | None = None) -> Quart:
    """Convenience: build everything from config and return a ready-to-run app."""
    config = config or Config()
    config.validate()

    stt = WhisperSTT(api_key=config.openai_api_key, model=config.stt_model)
    tts = OpenAITTS(
        api_key=config.openai_api_key,
        model=config.tts_model,
        voice=config.tts_voice,
    )
    agent = _build_agent(config)
    relay = Relay(stt=stt, tts=tts, agent=agent)

    return create_app(relay, config)
