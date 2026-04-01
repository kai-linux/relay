# relay

Voice bridge to CLI AI agents. Voice in, voice out, work synced over git.

## Architecture

- **relay/core.py** — Provider-agnostic pipeline: `audio → STT → agent → TTS → audio`. This is the embeddable heart of the project.
- **relay/stt.py, tts.py, agent.py** — Provider interfaces (ABCs) + implementations. Adding a new provider = subclass the ABC.
- **relay/app.py** — Thin Quart HTTP layer over the core. Two factory functions: `create_app()` (bring your own providers) and `create_app_from_config()` (everything from env vars).
- **relay/static/** — Minimal PWA frontend. Vanilla JS, Tailwind via CDN. Mobile-first, walk-and-talk optimized.

## Running

```bash
cp .env.example .env   # fill in OPENAI_API_KEY
pip install -e .
python run.py
```

## Design Principles

- Keep the core embeddable — no web framework imports in core.py, stt.py, tts.py, agent.py
- Providers are pluggable via ABCs — don't hardcode OpenAI/Claude assumptions outside their specific implementations
- Mobile-first — the primary use case is phone + headphones, not desktop
- Concise responses — the voice system prompt optimizes for spoken delivery

## Tech Stack

- Python 3.11+, Quart (async Flask), OpenAI API (Whisper + TTS)
- Frontend: static HTML/JS/Tailwind, PWA-capable
- Agent: Claude Code CLI via subprocess (default), extensible to others
