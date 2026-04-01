# relay

Voice bridge to CLI AI agents — voice in, voice out, work synced over git.

## The Idea

You're on a walk, headphones in. You talk to your AI coding agent — Claude Code, Codex, whatever — and it talks back. Concise, practical, spoken. Meanwhile, the actual work happens on a remote host: files get edited, tests get run, commits get pushed. Your working progress gets **relayed** from CLI to voice and back.

No screen. No keyboard. Just your voice and a capable agent that does the work while you think out loud.

```
You (voice, headphones)          Remote Host
┌──────────────┐                 ┌───────────────────────────┐
│  "Add input   │                 │                           │
│   validation  ├───► Whisper ───►│  Claude Code / Codex CLI  │
│   to the      │     (STT)      │  edits files, runs tests, │
│   signup      │                 │  commits & pushes via git │
│   form"       │◄─── TTS ◄──────┤                           │
│               │   (spoken)     │  "Done. Added email and   │
│  "Got it."    │                │   password validation to  │
│               │                │   the signup handler."    │
└──────────────┘                 └───────────────────────────┘
```

## Quick Start

```bash
git clone <this-repo> && cd relay
cp .env.example .env     # add your OPENAI_API_KEY
pip install -e .
python run.py
```

Open `http://<your-host>:5000` on your phone. Tap the button. Talk.

## How It Works

relay is a simple pipeline: **audio in → speech-to-text → AI agent → text-to-speech → audio out**.

1. You record a voice message on your phone (PWA, works in any browser)
2. Audio goes to the relay server running on your dev machine / remote host
3. OpenAI Whisper transcribes your speech to text
4. The text gets sent to Claude Code CLI, which executes your request — editing files, running commands, whatever you'd normally do at the terminal
5. The agent's response gets converted to speech via OpenAI TTS
6. You hear the response through your headphones

Git sync happens naturally — Claude Code commits and pushes as part of its workflow.

## Architecture

The core is designed to be **embeddable** — the relay pipeline is a plain Python class with no web framework dependencies:

```python
from relay import Relay, WhisperSTT, OpenAITTS, ClaudeCodeAgent

relay = Relay(
    stt=WhisperSTT(api_key="..."),
    tts=OpenAITTS(api_key="..."),
    agent=ClaudeCodeAgent(work_dir="/path/to/project"),
)

response = await relay.process(audio_bytes, session_id="abc")
# response.transcript — what you said
# response.text       — what the agent replied
# response.audio      — spoken reply (mp3 bytes)
```

Every component (STT, TTS, agent) is a pluggable provider behind an abstract interface. Swap OpenAI Whisper for local Whisper, or Claude Code for Codex, by implementing a single method.

```
relay/
├── relay/
│   ├── core.py          # Pipeline orchestrator (embeddable, no web deps)
│   ├── stt.py           # STT provider interface + Whisper implementation
│   ├── tts.py           # TTS provider interface + OpenAI implementation
│   ├── agent.py         # Agent interface + Claude Code CLI implementation
│   ├── app.py           # Quart HTTP layer (thin wrapper over core)
│   ├── config.py        # Configuration from environment
│   └── static/          # PWA frontend (vanilla JS, Tailwind)
├── run.py               # Entry point
├── pyproject.toml
└── .env.example
```

## Configuration

All configuration is via environment variables (or `.env` file):

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key for Whisper and TTS |
| `RELAY_STT_MODEL` | `whisper-1` | Whisper model |
| `RELAY_TTS_MODEL` | `tts-1` | TTS model (`tts-1` for speed, `tts-1-hd` for quality) |
| `RELAY_TTS_VOICE` | `nova` | Voice: alloy, echo, fable, onyx, nova, shimmer |
| `RELAY_WORK_DIR` | current directory | Working directory for the agent |
| `RELAY_AGENT_TIMEOUT` | `300` | Max seconds per agent request |
| `RELAY_HOST` | `0.0.0.0` | Server bind address |
| `RELAY_PORT` | `5000` | Server port |

## Prerequisites

- Python 3.11+
- An OpenAI API key (for Whisper STT and TTS)
- Claude Code CLI installed and authenticated on the host machine
- A git-managed project for the agent to work in

## Why This Exists

CLI AI agents like Claude Code and Codex are powerful — they read code, edit files, run tests, commit changes. But they're locked to the terminal. You have to be at your desk, staring at a screen.

Most of the value in a coding conversation is **directional** — "add validation to the signup form", "refactor the auth middleware", "what's the status of the test suite". You don't need to see every line of the diff in real time. You need a concise summary of what was done, and confidence that the agent did it right.

relay makes that possible over voice. Walk the dog, ride the bus, do the dishes — and keep your project moving.

## Possible Futures

This pattern — voice as a universal interface to AI agents — goes beyond developer tooling:

- **Vibecoding for kids** — children who can't read or write yet could build software by talking to an agent. "Make the character jump higher." "Add a rainbow background." Voice in, voice out, with a live preview.
- **Embedded voice layer** — relay's core is a standalone Python library. Drop it into any app that needs a voice-to-agent bridge.
- **Managed service** — hosted relay as an API, so developers don't have to run their own server.

## What's Next

This is v0.1. The foundation is here; there's more to build:

- **Streaming responses** — start hearing the reply before the agent finishes (TTS chunking)
- **Multi-turn conversation** — resume Claude Code sessions across messages
- **Voice activity detection** — hands-free, no tap needed
- **Agent backends** — Codex CLI, direct API calls, Aider, custom agents
- **Local STT/TTS** — run fully offline with local Whisper + Piper
- **Auth and multi-user** — secure access when exposed beyond localhost
- **Mobile notifications** — push when long-running tasks complete

## License

Apache 2.0 — see [LICENSE](LICENSE).
