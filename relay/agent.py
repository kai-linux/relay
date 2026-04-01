"""Agent backends — CLI AI tool integrations."""

import asyncio
from abc import ABC, abstractmethod


class AgentBackend(ABC):
    """Base class for AI agent backends.

    Subclass this to add new agent integrations (e.g. Aider, a direct API call).
    """

    @abstractmethod
    async def send(self, message: str, session_id: str) -> str:
        """Send a message to the agent and return its text response."""
        ...


VOICE_SYSTEM_PROMPT = (
    "The user is talking to you via voice while away from their keyboard. "
    "Keep responses concise and natural for spoken delivery. "
    "Avoid markdown formatting, code fences, bullet lists, and special characters. "
    "When you perform actions like editing files or running commands, "
    "summarize what you did in one to three short sentences. "
    "If you need to share code, keep it to the essential lines only."
)


class ClaudeCodeAgent(AgentBackend):
    """Runs Claude Code CLI as a subprocess."""

    def __init__(self, work_dir: str = ".", timeout: int = 300,
                 skip_permissions: bool = False):
        self.work_dir = work_dir
        self.timeout = timeout
        self.skip_permissions = skip_permissions

    async def send(self, message: str, session_id: str) -> str:
        cmd = [
            "claude",
            "-p",
            "--output-format", "text",
            "--append-system-prompt", VOICE_SYSTEM_PROMPT,
        ]
        if self.skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        cmd.append(message)

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
            return "The agent timed out. Try a simpler request or increase the timeout."

        response = stdout.decode().strip()
        if proc.returncode != 0 and not response:
            err = stderr.decode().strip()
            return f"Agent error: {err}" if err else "Agent returned an error with no output."

        return response


class CodexAgent(AgentBackend):
    """Runs OpenAI Codex CLI as a subprocess."""

    def __init__(self, work_dir: str = ".", timeout: int = 300,
                 skip_permissions: bool = False):
        self.work_dir = work_dir
        self.timeout = timeout
        self.skip_permissions = skip_permissions

    async def send(self, message: str, session_id: str) -> str:
        cmd = ["codex", "--quiet"]
        if self.skip_permissions:
            cmd.extend(["--approval-mode", "full-auto"])
        cmd.extend(["--prompt", message])

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
            return "The agent timed out. Try a simpler request or increase the timeout."

        response = stdout.decode().strip()
        if proc.returncode != 0 and not response:
            err = stderr.decode().strip()
            return f"Agent error: {err}" if err else "Agent returned an error with no output."

        return response
