import argparse
import json
import os
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "config.json")
)


class DaemonConfig:
    """Manages the configuration options for the eUczelniaDaemon.

    Loads defaults from config.json, merges CLI arguments, and holds
    runtime-mutable state (like the current model or user prompt).
    """

    def __init__(self) -> None:
        self.poll_interval_seconds: float = 12.0
        self.mode: str = "stateless"
        self.max_history_turns: int = 20
        self.cleanup_on_disconnect: bool = False
        self.command_prefix: str = "!"
        self.sentinel_start: str = "«AI»"
        self.sentinel_end: str = "«/AI»"
        self.data_dir: str = "./data"
        self.knowledge_files: List[str] = []
        self.engine: str = "hermes"

        self.ai_gateway: Dict[str, Any] = {
            "base_url": "http://localhost:11434/v1",
            "api_key": "local-key",
            "model": "gpt-4o-mini",
        }

        # CLI-provided values (session specific)
        self.conversation_id: Optional[int] = None
        self.sesskey: Optional[str] = None
        self.cookie_name: Optional[str] = None
        self.cookie_value: Optional[str] = None
        self.user_id: Optional[int] = None

        # Base user instructions/prompts
        self.user_base_prompt: str = ""
        self._user_prompt_backup: Optional[str] = None

    @property
    def model(self) -> str:
        """Get the current AI model."""
        return self.ai_gateway.get("model", "gpt-4o-mini")

    @model.setter
    def model(self, value: str) -> None:
        """Set the current AI model."""
        self.ai_gateway["model"] = value

    def load_from_json(self, filepath: str) -> None:
        """Loads configuration options from a JSON file.

        Args:
            filepath: Path to the config.json file.
        """
        if not os.path.exists(filepath):
            return

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.poll_interval_seconds = float(
            data.get("poll_interval_seconds", self.poll_interval_seconds)
        )
        self.mode = str(data.get("mode", self.mode))
        self.max_history_turns = int(data.get("max_history_turns", self.max_history_turns))
        self.cleanup_on_disconnect = bool(
            data.get("cleanup_on_disconnect", self.cleanup_on_disconnect)
        )
        self.command_prefix = str(data.get("command_prefix", self.command_prefix))
        self.sentinel_start = str(data.get("sentinel_start", self.sentinel_start))
        self.sentinel_end = str(data.get("sentinel_end", self.sentinel_end))
        self.data_dir = str(data.get("data_dir", self.data_dir))
        self.engine = str(data.get("engine", self.engine))
        
        # Load knowledge files if configured in JSON
        if "knowledge_files" in data:
            self.knowledge_files = list(data["knowledge_files"])

        if "ai_gateway" in data and isinstance(data["ai_gateway"], dict):
            self.ai_gateway.update(data["ai_gateway"])

    def set_user_prompt(self, prompt: str) -> None:
        """Sets the user base prompt, backing up the current one.

        Args:
            prompt: The new user base prompt.
        """
        self._user_prompt_backup = self.user_base_prompt
        self.user_base_prompt = prompt

    def append_user_prompt(self, prompt: str) -> None:
        """Appends text to the user base prompt, backing up the current one.

        Args:
            prompt: The text to append.
        """
        self._user_prompt_backup = self.user_base_prompt
        if self.user_base_prompt:
            self.user_base_prompt += "\n" + prompt
        else:
            self.user_base_prompt = prompt

    def undo_user_prompt(self) -> bool:
        """Restores the previous user base prompt.

        Returns:
            True if restored, False if there was no backup.
        """
        if self._user_prompt_backup is not None:
            self.user_base_prompt = self._user_prompt_backup
            self._user_prompt_backup = None
            return True
        return False


def parse_args_and_load_config(argv: List[str]) -> DaemonConfig:
    """Parses command-line arguments and loads JSON configuration.

    Args:
        argv: Command line arguments list (excluding script name).

    Returns:
        An initialized DaemonConfig instance.
    """
    parser = argparse.ArgumentParser(
        description="eUczelniaDaemon - Moodle messenger bridge to OpenAI-compatible AI gateway."
    )
    parser.add_argument("--conversation-id", type=int, help="Moodle conversation ID to monitor.")
    parser.add_argument("--sesskey", type=str, help="Moodle session key.")
    parser.add_argument(
        "--cookie-name",
        type=str,
        help="Moodle session cookie name (e.g., MoodleSessionmdlprod).",
    )
    parser.add_argument("--cookie-value", type=str, help="Moodle session cookie value.")
    parser.add_argument("--user-id", type=int, help="Moodle user ID of the daemon's account.")
    parser.add_argument("--user-prompt", type=str, help="Initial user base prompt.")
    parser.add_argument("--config", type=str, default=DEFAULT_CONFIG_PATH, help="Path to config.json.")
    parser.add_argument("--data-dir", type=str, help="Directory for writing database, status, and logs.")
    parser.add_argument(
        "--engine",
        choices=["hermes", "openai"],
        help="The completions engine backend (hermes or openai)."
    )
    parser.add_argument(
        "--knowledge-file",
        action="append",
        dest="knowledge_files",
        default=[],
        help="Path to a text/markdown file to load into the knowledge base (can be repeated)."
    )

    args = parser.parse_args(argv)

    config = DaemonConfig()
    if args.config:
        config.load_from_json(args.config)

    # CLI arguments override JSON config values
    if args.conversation_id is not None:
        config.conversation_id = args.conversation_id
    if args.sesskey is not None:
        config.sesskey = args.sesskey
    if args.cookie_name is not None:
        config.cookie_name = args.cookie_name
    if args.cookie_value is not None:
        config.cookie_value = args.cookie_value
    if args.user_id is not None:
        config.user_id = args.user_id
    if args.user_prompt is not None:
        config.user_base_prompt = args.user_prompt
    if args.data_dir is not None:
        config.data_dir = args.data_dir
    if args.engine is not None:
        config.engine = args.engine
    if args.knowledge_files:
        # Extend configured knowledge files with CLI ones
        config.knowledge_files.extend(args.knowledge_files)

    return config
