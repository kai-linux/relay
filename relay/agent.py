"""Agent backends — CLI AI tool integrations."""

import asyncio
import json
import logging
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


_TOOL_LABELS = {
    "Read": "I'm reading through the files now",
    "Write": "I'm writing some code",
    "Edit": "I'm making some edits",
    "Bash": "I'm running a command",
    "Grep": "I'm searching the codebase",
    "Glob": "I'm looking for the right files",
    "Agent": "I'm kicking off a sub-task",
    "WebFetch": "I'm pulling up a web page",
    "WebSearch": "I'm searching the web for that",
}


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
                return "Let me think about this..."

            if part_type == "tool_use":
                tool = part.get("name", "")
                if tool in seen_tools:
                    continue
                seen_tools.add(tool)
                return _TOOL_LABELS.get(tool, f"I'm using {tool}")

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
                    return "Thinking..."

        if msg_type == "function_call":
            name = msg.get("name", "")
            label = _TOOL_LABELS.get(name, "")
            if label:
                return label
            if name:
                return f"Using {name}"

        return None
