from typing import Callable, Tuple
from daemon.config import DaemonConfig
from daemon.db import DatabaseManager


def is_command(text: str, prefix: str) -> bool:
    """Checks if a message starts with the command prefix.

    Args:
        text: The message content.
        prefix: The command prefix.

    Returns:
        True if the message is a command, False otherwise.
    """
    return text.strip().startswith(prefix)


def parse_command(text: str, prefix: str) -> Tuple[str, str]:
    """Splits a command message into its command name and arguments.

    Args:
        text: The command message text.
        prefix: The command prefix.

    Returns:
        A tuple of (command_name, args_string).
    """
    content = text.strip()[len(prefix) :].strip()
    if not content:
        return "", ""
    parts = content.split(maxsplit=1)
    cmd_name = parts[0].lower()
    args_str = parts[1] if len(parts) > 1 else ""
    return cmd_name, args_str


class CommandHandler:
    """Dispatches and executes in-chat commands."""

    def __init__(
        self,
        config: DaemonConfig,
        db: DatabaseManager,
        conversation_id: int,
        get_uptime_seconds: Callable[[], float],
        get_message_count: Callable[[], int],
        clear_context_callback: Callable[[], None],
        shutdown_callback: Callable[[], None],
        get_knowledge_summary: Callable[[], str],
    ) -> None:
        """Initializes the CommandHandler.

        Args:
            config: The DaemonConfig configuration.
            db: The DatabaseManager.
            conversation_id: The active conversation ID.
            get_uptime_seconds: Callback returning daemon uptime.
            get_message_count: Callback returning current session message count.
            clear_context_callback: Callback executing clear history.
            shutdown_callback: Callback executing graceful shutdown.
            get_knowledge_summary: Callback returning knowledge files summary.
        """
        self.config = config
        self.db = db
        self.conversation_id = conversation_id
        self.get_uptime_seconds = get_uptime_seconds
        self.get_message_count = get_message_count
        self.clear_context_callback = clear_context_callback
        self.shutdown_callback = shutdown_callback
        self.get_knowledge_summary = get_knowledge_summary

    def execute(self, text: str) -> str:
        """Parses and executes a command string, returning a text response.

        Args:
            text: The raw command string.

        Returns:
            The reply text to send back to Moodle.
        """
        cmd_name, args_str = parse_command(text, self.config.command_prefix)
        if not cmd_name:
            return "Unknown command."

        if cmd_name == "help":
            return self._cmd_help()
        elif cmd_name == "status":
            return self._cmd_status()
        elif cmd_name == "mode":
            return self._cmd_mode(args_str)
        elif cmd_name == "clear":
            return self._cmd_clear()
        elif cmd_name == "model":
            return self._cmd_model(args_str)
        elif cmd_name == "cleanup":
            return self._cmd_cleanup(args_str)
        elif cmd_name == "prompt":
            return self._cmd_prompt(args_str)
        elif cmd_name == "knowledge":
            return self._cmd_knowledge(args_str)
        elif cmd_name == "disconnect":
            return self._cmd_disconnect()
        else:
            p = self.config.command_prefix
            return f"Unknown command: {cmd_name}. Type {p}help for a list of available commands."

    def _cmd_help(self) -> str:
        p = self.config.command_prefix
        return (
            "Available commands:\n"
            f"- {p}help: Show this help message\n"
            f"- {p}status: Show status info\n"
            f"- {p}mode <stateless|context>: Switch mode\n"
            f"- {p}clear: Clear context history\n"
            f"- {p}model <name>: Change AI model\n"
            f"- {p}cleanup <on|off>: Toggle cleanup on disconnect\n"
            f"- {p}prompt show: Display current user base prompt\n"
            f"- {p}prompt set <text>: Set user base prompt\n"
            f"- {p}prompt append <text>: Append to user base prompt\n"
            f"- {p}prompt undo: Restore previous user base prompt\n"
            f"- {p}knowledge show: Display loaded knowledge files\n"
            f"- {p}disconnect: Gracefully shut down daemon"
        )

    def _cmd_status(self) -> str:
        uptime_sec = self.get_uptime_seconds()
        hours, rem = divmod(int(uptime_sec), 3600)
        minutes, seconds = divmod(rem, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"
        msg_count = self.get_message_count()

        return (
            "Status:\n"
            f"- Mode: {self.config.mode}\n"
            f"- Model: {self.config.model}\n"
            f"- Cleanup: {'on' if self.config.cleanup_on_disconnect else 'off'}\n"
            f"- Messages in session: {msg_count}\n"
            f"- Uptime: {uptime_str}"
        )

    def _cmd_mode(self, args_str: str) -> str:
        mode = args_str.strip().lower()
        if mode == "stateless":
            self.config.mode = "stateless"
            return "Mode switched to stateless."
        elif mode == "context":
            self.config.mode = "context"
            return "Mode switched to context."
        else:
            return f"Invalid mode: '{args_str}'. Use 'stateless' or 'context'."

    def _cmd_clear(self) -> str:
        if self.config.mode != "context":
            return "Clear command is only available in context mode."
        self.clear_context_callback()
        return "Context history cleared."

    def _cmd_model(self, args_str: str) -> str:
        model_name = args_str.strip()
        if not model_name:
            return "Model name cannot be empty."
        self.config.model = model_name
        return f"Model changed to {model_name}."

    def _cmd_cleanup(self, args_str: str) -> str:
        opt = args_str.strip().lower()
        if opt == "on":
            self.config.cleanup_on_disconnect = True
            return "Message cleanup on disconnect enabled."
        elif opt == "off":
            self.config.cleanup_on_disconnect = False
            return "Message cleanup on disconnect disabled."
        else:
            return f"Invalid option: '{args_str}'. Use 'on' or 'off'."

    def _cmd_prompt(self, args_str: str) -> str:
        parts = args_str.split(maxsplit=1)
        subcmd = parts[0].lower() if parts else ""
        text = parts[1].strip() if len(parts) > 1 else ""

        if subcmd == "show":
            if not self.config.user_base_prompt:
                return "No base prompt is currently set."
            return f"Current base prompt:\n{self.config.user_base_prompt}"

        elif subcmd == "set":
            if not text:
                return "Prompt text cannot be empty."
            self.config.set_user_prompt(text)
            self.db.set_active_prompt(self.conversation_id, text)
            return "Base prompt set."

        elif subcmd == "append":
            if not text:
                return "Prompt text cannot be empty."
            self.config.append_user_prompt(text)
            self.db.set_active_prompt(self.conversation_id, self.config.user_base_prompt)
            return "Base prompt updated."

        elif subcmd == "undo":
            reverted = self.db.undo_active_prompt(self.conversation_id)
            if reverted is not None:
                self.config.user_base_prompt = reverted
                self.config._user_prompt_backup = None
                return f"Base prompt reverted to: {reverted}"
            else:
                self.config.user_base_prompt = ""
                self.config._user_prompt_backup = None
                return "Base prompt cleared (no previous prompt found)."
        else:
            return "Invalid prompt subcommand. Use 'show', 'set <text>', 'append <text>', or 'undo'."

    def _cmd_knowledge(self, args_str: str) -> str:
        subcmd = args_str.strip().lower()
        if not subcmd or subcmd == "show":
            return self.get_knowledge_summary()
        else:
            return "Invalid knowledge subcommand. Use 'show'."

    def _cmd_disconnect(self) -> str:
        self.shutdown_callback()
        return "Disconnecting..."
