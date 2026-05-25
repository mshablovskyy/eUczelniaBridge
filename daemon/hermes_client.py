import os
import sys
import shutil
import asyncio
import logging
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HermesClient:
    """Routes chat completion queries into the local Hermes agent loop CLI subprocess.

    Serializes system instructions, context, user prompts, and conversation history
    into a structured query block, then calls `hermes chat` headlessly.
    """

    def __init__(self) -> None:
        self.hermes_path = self._resolve_hermes_path()
        logger.info(f"Initialized HermesClient using binary: {self.hermes_path}")

    def _resolve_hermes_path(self) -> str:
        """Dynamically resolve the location of the hermes CLI binary."""
        # 1. Check environment variable
        env_path = os.getenv("HERMES_BIN")
        if env_path:
            if os.path.exists(env_path):
                return env_path
            logger.warning(f"HERMES_BIN env var set to '{env_path}' but file does not exist.")

        # 2. Check system PATH via shutil.which
        which_path = shutil.which("hermes")
        if which_path:
            return which_path

        # 3. Check common default paths
        default_paths = [
            "~/.hermes/hermes-agent/venv/bin/hermes",
            "~/.gemini/hermes-agent/venv/bin/hermes",
        ]
        for dp in default_paths:
            resolved = os.path.abspath(os.path.expanduser(dp))
            if os.path.exists(resolved):
                return resolved

        # 4. Fallback to default name and hope it executes in environment
        return "hermes"

    async def answer(
        self,
        batch_text: str,
        history: Optional[List[Dict[str, Any]]],
        system_prompt: str,
        user_prompt: str,
        model: str,
        knowledge_context: Optional[str] = None,
    ) -> str:
        """Format the input text with prompts and history, then invoke Hermes."""
        query_parts = []

        # System instructions
        system_instruction = system_prompt or ""
        if knowledge_context:
            system_instruction += f"\n\nRelevant knowledge context:\n{knowledge_context}"
        if user_prompt:
            system_instruction += f"\n\nUser instructions for this session:\n{user_prompt}"

        if system_instruction:
            query_parts.append(system_instruction)

        # Conversation history mapping
        if history:
            history_lines = ["Conversation history:"]
            for h in history:
                role = h.get("role", "user")
                content = h.get("content", "")
                history_lines.append(f"<{role}>: {content}")
            query_parts.append("\n".join(history_lines))

        # Current new message
        query_parts.append(f"New message from the chat:\n{batch_text}")

        # Combine everything
        full_query = "\n\n---\n\n".join(query_parts)

        # Invoke the CLI subprocess with retry-once
        try:
            return await self._execute_hermes_subprocess(full_query)
        except Exception as e:
            logger.warning(f"Hermes execution failed with error: {e}. Retrying once...")
            return await self._execute_hermes_subprocess(full_query)

    async def _execute_hermes_subprocess(self, query: str) -> str:
        """Run the hermes CLI subprocess asynchronously and capture response."""
        args = [
            self.hermes_path,
            "chat",
            "-q",
            query,
            "--yolo",
            "-Q",
        ]

        logger.info(f"Launching Hermes subprocess: {' '.join(args[:4])} ...")
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        try:
            # 5 minutes (300s) timeout to allow execution of tools/skills
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise RuntimeError("Hermes CLI subprocess execution timed out after 300 seconds.")

        if proc.returncode != 0:
            raise RuntimeError(f"Hermes CLI process failed with exit code: {proc.returncode}")

        output = stdout.decode("utf-8", errors="replace").strip()
        return output
