"""Agent backends — CLI AI tool integrations."""

import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

log = logging.getLogger(__name__)

# 4 MB — stream-json result lines can be very large for long agent responses
_STREAM_BUFFER_LIMIT = 4 * 1024 * 1024


class AgentError(Exception):
    """Raised when an agent fails in a way that warrants trying a fallback."""


@dataclass
class AgentEvent:
    """A progress event emitted by an agent during processing."""

    type: str  # "status" or "result"
    text: str


class AgentBackend(ABC):
    """Base class for AI agent backends.

    Subclass this to add new agent integrations (e.g. Aider, a direct API call).
    """

    @abstractmethod
    async def send(self, message: str, session_id: str) -> str:
        """Send a message to the agent and return its text response.

        Raise AgentError if the agent fails and a fallback should be tried.
        """
        ...

    async def send_stream(
        self, message: str, session_id: str
    ) -> AsyncIterator[AgentEvent]:
        """Stream progress events, ending with a 'result' event.

        Default implementation wraps send() with no intermediate updates.
        """
        result = await self.send(message, session_id)
        yield AgentEvent(type="result", text=result)


VOICE_SYSTEM_PROMPT = (
    "The user is talking to you via voice while away from their keyboard. "
    "Keep responses concise and natural for spoken delivery. "
    "Avoid markdown formatting, code fences, bullet lists, and special characters. "
    "When you perform actions like editing files or running commands, "
    "summarize what you did in one to three short sentences. "
    "If you need to share code, keep it to the essential lines only."
)


class FallbackAgent(AgentBackend):
    """Tries agents in order, falling back to the next on failure."""

    def __init__(self, agents: list[AgentBackend]):
        if not agents:
            raise ValueError("FallbackAgent needs at least one agent")
        self.agents = agents

    async def send(self, message: str, session_id: str) -> str:
        last_err = None
        for i, agent in enumerate(self.agents):
            name = type(agent).__name__
            try:
                return await agent.send(message, session_id)
            except AgentError as e:
                last_err = e
                remaining = len(self.agents) - i - 1
                if remaining:
                    log.warning("%s failed (%s), trying next backend", name, e)
                else:
                    log.error("%s failed (%s), no more backends", name, e)
        return f"All agents failed. Last error: {last_err}"

    async def send_stream(
        self, message: str, session_id: str
    ) -> AsyncIterator[AgentEvent]:
        last_err = None
        for i, agent in enumerate(self.agents):
            name = type(agent).__name__
            try:
                async for event in agent.send_stream(message, session_id):
                    yield event
                return
            except AgentError as e:
                last_err = e
                remaining = len(self.agents) - i - 1
                if remaining:
                    log.warning("%s failed (%s), trying next backend", name, e)
                else:
                    log.error("%s failed (%s), no more backends", name, e)
        yield AgentEvent(type="result", text=f"All agents failed. Last error: {last_err}")


# ---------------------------------------------------------------------------
# Combinatorial voice status messages
# ---------------------------------------------------------------------------
# Each tool maps to (verbs, objects) tuples.  We pick one verb + one object
# at random, giving  V × O  unique phrases per tool — hundreds of distinct
# status messages overall, with zero repetition within a session thanks to
# the seen_tools gate.

_TOOL_PHRASES: dict[str, tuple[list[str], list[str]]] = {
    "Read": (
        ["Reading through", "Looking at", "Checking", "Reviewing",
         "Scanning", "Pulling up", "Opening", "Inspecting"],
        ["the files now", "the source code", "what we've got",
         "the relevant files", "that file", "the code"],
    ),
    "Write": (
        ["Writing", "Putting together", "Drafting", "Creating",
         "Generating", "Setting up", "Laying down"],
        ["some code", "a new file", "the implementation",
         "the code for that", "what's needed", "the changes"],
    ),
    "Edit": (
        ["Making", "Applying", "Working on", "Putting in",
         "Dropping in", "Tweaking", "Adjusting"],
        ["some edits", "the changes", "a few modifications",
         "the updates", "the fix", "the adjustments"],
    ),
    "Bash": (
        ["Running", "Firing off", "Executing", "Kicking off",
         "Launching", "Spinning up"],
        ["a command", "a shell command", "something in the terminal",
         "a quick command", "that in the terminal", "a process"],
    ),
    "Grep": (
        ["Searching", "Scanning", "Combing through", "Looking through",
         "Hunting through", "Sifting through", "Digging into"],
        ["the codebase", "the source", "the files",
         "the code for that", "for matches", "for references"],
    ),
    "Glob": (
        ["Looking for", "Tracking down", "Locating", "Hunting for",
         "Searching for", "Finding"],
        ["the right files", "matching files", "the files we need",
         "what's relevant", "the target files", "the file paths"],
    ),
    "Agent": (
        ["Kicking off", "Spinning up", "Dispatching", "Launching",
         "Starting", "Handing off to"],
        ["a sub-task", "a background task", "a helper agent",
         "a parallel task", "an assistant", "a sub-agent"],
    ),
    "WebFetch": (
        ["Pulling up", "Fetching", "Grabbing", "Loading",
         "Retrieving", "Opening"],
        ["a web page", "that page", "the URL", "some info online",
         "the link", "the resource"],
    ),
    "WebSearch": (
        ["Searching", "Looking up", "Querying", "Checking",
         "Scouring", "Browsing"],
        ["the web for that", "the internet", "online for answers",
         "the web", "for results online", "for that info"],
    ),
}

_THINKING_PHRASES: list[str] = [
    "Let me think about this...",
    "Thinking it over...",
    "Give me a moment to consider this...",
    "Working through this...",
    "Let me reason through that...",
    "Mulling this over...",
    "Processing that...",
    "Let me work through this...",
    "Considering the options...",
    "Turning this over in my mind...",
    "One moment while I think...",
    "Let me figure this out...",
]


def _pick_tool_label(tool: str) -> str:
    """Return a varied status phrase for a tool invocation."""
    phrases = _TOOL_PHRASES.get(tool)
    if not phrases:
        return f"I'm using {tool}"
    verb = random.choice(phrases[0])
    obj = random.choice(phrases[1])
    return f"{verb} {obj}"


def _pick_thinking_label() -> str:
    """Return a varied thinking status phrase."""
    return random.choice(_THINKING_PHRASES)


class ClaudeCodeAgent(AgentBackend):
    """Runs Claude Code CLI as a subprocess."""

    def __init__(self, work_dir: str = ".", timeout: int = 300):
        self.work_dir = work_dir
        self.timeout = timeout
        self._started_sessions: set[str] = set()

    def _build_cmd(self, message: str, continue_mode: bool) -> list[str]:
        return [
            "claude",
            "-c" if continue_mode else "-p",
            "--dangerously-skip-permissions",
            "--verbose",
            "--output-format", "stream-json",
            "--append-system-prompt", VOICE_SYSTEM_PROMPT,
            message,
        ]

    async def send(self, message: str, session_id: str) -> str:
        result = ""
        async for event in self.send_stream(message, session_id):
            if event.type == "result":
                result = event.text
        return result

    async def send_stream(
        self, message: str, session_id: str
    ) -> AsyncIterator[AgentEvent]:
        continue_mode = session_id in self._started_sessions
        cmd = self._build_cmd(message, continue_mode)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.work_dir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_BUFFER_LIMIT,
        )

        result_text = ""
        seen_tools: set[str] = set()

        try:
            deadline = asyncio.get_event_loop().time() + self.timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    proc.kill()
                    await proc.wait()
                    raise AgentError("timed out")

                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=remaining
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    raise AgentError("timed out")

                if not line:
                    break

                line = line.decode().strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                status = self._extract_status(msg, seen_tools)
                if status:
                    yield AgentEvent(type="status", text=status)

                if msg.get("type") == "result":
                    result_text = msg.get("result", result_text)

        except AgentError:
            raise
        except Exception as e:
            proc.kill()
            await proc.wait()
            raise AgentError(str(e))

        await proc.wait()

        # If -c failed (no prior conversation), fall back to -p
        if not result_text and proc.returncode != 0 and continue_mode:
            stderr_out = await proc.stderr.read()
            log.info("Continue failed (%s), starting new conversation",
                     stderr_out.decode().strip()[:100])
            self._started_sessions.discard(session_id)
            async for event in self.send_stream(message, session_id):
                yield event
            return

        if not result_text and proc.returncode != 0:
            stderr_out = await proc.stderr.read()
            err = stderr_out.decode().strip()
            raise AgentError(err or f"exit code {proc.returncode}")

        self._started_sessions.add(session_id)
        yield AgentEvent(type="result", text=result_text)

    @staticmethod
    def _extract_status(msg: dict, seen_tools: set[str]) -> str | None:
        # stream-json wraps content inside {"type": "assistant", "message": {"content": [...]}}
        if msg.get("type") != "assistant":
            return None

        content = msg.get("message", {}).get("content", [])
        for part in content:
            part_type = part.get("type")

            if part_type == "thinking":
                return _pick_thinking_label()

            if part_type == "tool_use":
                tool = part.get("name", "")
                if tool in seen_tools:
                    continue
                seen_tools.add(tool)
                return _pick_tool_label(tool)

        return None


class CodexAgent(AgentBackend):
    """Runs OpenAI Codex CLI as a subprocess."""

    def __init__(self, work_dir: str = ".", timeout: int = 300):
        self.work_dir = work_dir
        self.timeout = timeout
        self._started_sessions: set[str] = set()

    def _build_cmd(self, message: str, continue_mode: bool) -> list[str]:
        if continue_mode:
            return [
                "codex", "exec", "resume", "--last",
                "--dangerously-bypass-approvals-and-sandbox",
                "--json",
                message,
            ]
        return [
            "codex", "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            message,
        ]

    async def send(self, message: str, session_id: str) -> str:
        result = ""
        async for event in self.send_stream(message, session_id):
            if event.type == "result":
                result = event.text
        return result

    async def send_stream(
        self, message: str, session_id: str
    ) -> AsyncIterator[AgentEvent]:
        continue_mode = session_id in self._started_sessions
        cmd = self._build_cmd(message, continue_mode)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.work_dir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_BUFFER_LIMIT,
        )

        result_text = ""

        try:
            deadline = asyncio.get_event_loop().time() + self.timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    proc.kill()
                    await proc.wait()
                    raise AgentError("timed out")

                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=remaining
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    raise AgentError("timed out")

                if not line:
                    break

                line = line.decode().strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                status = self._extract_status(msg)
                if status:
                    yield AgentEvent(type="status", text=status)

                if msg.get("type") == "message" and msg.get("role") == "assistant":
                    content = msg.get("content", [])
                    for part in content:
                        if part.get("type") == "output_text":
                            result_text = part.get("text", result_text)

        except AgentError:
            raise
        except Exception as e:
            proc.kill()
            await proc.wait()
            raise AgentError(str(e))

        await proc.wait()

        # If resume --last failed (no prior session), fall back to plain exec
        if not result_text and proc.returncode != 0 and continue_mode:
            stderr_out = await proc.stderr.read()
            log.info("Codex resume failed (%s), starting new session",
                     stderr_out.decode().strip()[:100])
            self._started_sessions.discard(session_id)
            async for event in self.send_stream(message, session_id):
                yield event
            return

        if not result_text and proc.returncode != 0:
            stderr_out = await proc.stderr.read()
            err = stderr_out.decode().strip()
            raise AgentError(err or f"exit code {proc.returncode}")

        self._started_sessions.add(session_id)
        yield AgentEvent(type="result", text=result_text)

    @staticmethod
    def _extract_status(msg: dict) -> str | None:
        msg_type = msg.get("type")

        if msg_type == "message" and msg.get("role") == "assistant":
            content = msg.get("content", [])
            for part in content:
                if part.get("type") == "thinking":
                    return _pick_thinking_label()

        if msg_type == "function_call":
            name = msg.get("name", "")
            if name:
                return _pick_tool_label(name)

        return None
