"""Agent backends — CLI AI tool integrations."""

import asyncio
import logging
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class AgentError(Exception):
    """Raised when an agent fails in a way that warrants trying a fallback."""


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


class ClaudeCodeAgent(AgentBackend):
    """Runs Claude Code CLI as a subprocess."""

    def __init__(self, work_dir: str = ".", timeout: int = 300):
        self.work_dir = work_dir
        self.timeout = timeout
        self._started_sessions: set[str] = set()

    async def send(self, message: str, session_id: str) -> str:
        # First message in a session: -p (new conversation)
        # Subsequent messages: -c (continue most recent conversation)
        if session_id in self._started_sessions:
            mode_flag = "-c"
        else:
            mode_flag = "-p"
            self._started_sessions.add(session_id)

        cmd = [
            "claude",
            mode_flag,
            "--dangerously-skip-permissions",
            "--output-format", "text",
            "--append-system-prompt", VOICE_SYSTEM_PROMPT,
            message,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise AgentError("timed out")

        response = stdout.decode().strip()
        err = stderr.decode().strip()

        if proc.returncode != 0 and not response:
            raise AgentError(err or f"exit code {proc.returncode}")

        return response


class CodexAgent(AgentBackend):
    """Runs OpenAI Codex CLI as a subprocess."""

    def __init__(self, work_dir: str = ".", timeout: int = 300):
        self.work_dir = work_dir
        self.timeout = timeout
        self._started_sessions: set[str] = set()

    async def send(self, message: str, session_id: str) -> str:
        # First message: codex exec (new conversation)
        # Subsequent messages: codex exec resume --last (continue)
        if session_id in self._started_sessions:
            cmd = [
                "codex", "exec", "resume", "--last",
                "--dangerously-bypass-approvals-and-sandbox",
                message,
            ]
        else:
            self._started_sessions.add(session_id)
            cmd = [
                "codex", "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                message,
            ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise AgentError("timed out")

        response = stdout.decode().strip()
        err = stderr.decode().strip()

        if proc.returncode != 0 and not response:
            raise AgentError(err or f"exit code {proc.returncode}")

        return response
