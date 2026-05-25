import asyncio
import html
import json
import logging
import logging.handlers
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional, Set

from eUczelniaMessenger import MessengerClient, SessionData  # type: ignore[attr-defined]
from eUczelniaMessenger.errors import MoodleAPIError
from eUczelniaMessenger.models import SendResult

from daemon.config import DaemonConfig, parse_args_and_load_config
from daemon.db import DatabaseManager
from daemon.ai_client import AIClient
from daemon.hermes_client import HermesClient
from daemon.commands import CommandHandler, is_command, parse_command
from daemon.knowledge import KnowledgeBase

logger = logging.getLogger("eUczelniaDaemon")


def extract_message_id(send_result: SendResult) -> Optional[int]:
    """Extracts the message ID from a Moodle SendResult.

    Handles differences in list/dictionary responses and key names.
    """
    raw = send_result.raw
    if isinstance(raw, list):
        if len(raw) > 0:
            item = raw[0]
            if isinstance(item, dict):
                val = item.get("id") or item.get("msgid")
                if val is not None:
                    return int(val)
    elif isinstance(raw, dict):
        val = raw.get("id") or raw.get("msgid")
        if val is not None:
            return int(val)
        msgs = raw.get("messages")
        if isinstance(msgs, list) and msgs:
            val = msgs[0].get("id") or msgs[0].get("msgid")
            if val is not None:
                return int(val)
    return None


def split_message_text(text: str, max_bytes: int = 3900) -> list[str]:
    """Intelligently splits a message into chunks that fit within max_bytes.

    Splits at paragraphs (newlines), sentence boundaries, words (spaces), or characters,
    in that order of preference.
    """
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    # Step 1: Split by newlines (paragraphs)
    parts = text.split("\n")
    if len(parts) > 1:
        chunks = []
        current_part: list[str] = []
        current_len = 0
        for part in parts:
            part_len = len(part.encode("utf-8"))
            if part_len > max_bytes:
                if current_part:
                    chunks.append("\n".join(current_part))
                    current_part = []
                    current_len = 0
                chunks.extend(split_message_text(part, max_bytes))
            else:
                sep_len = 1 if current_part else 0
                if current_len + sep_len + part_len <= max_bytes:
                    current_part.append(part)
                    current_len += sep_len + part_len
                else:
                    chunks.append("\n".join(current_part))
                    current_part = [part]
                    current_len = part_len
        if current_part:
            chunks.append("\n".join(current_part))
        return chunks

    # Step 2: Split by sentence boundaries (periods, exclamation, question marks followed by space)
    sentence_parts = re.split(r"(?<=[.!?])\s+", text)
    if len(sentence_parts) > 1:
        chunks = []
        current_part = []
        current_len = 0
        for part in sentence_parts:
            part_len = len(part.encode("utf-8"))
            if part_len > max_bytes:
                if current_part:
                    chunks.append(" ".join(current_part))
                    current_part = []
                    current_len = 0
                chunks.extend(split_message_text(part, max_bytes))
            else:
                sep_len = 1 if current_part else 0
                if current_len + sep_len + part_len <= max_bytes:
                    current_part.append(part)
                    current_len += sep_len + part_len
                else:
                    chunks.append(" ".join(current_part))
                    current_part = [part]
                    current_len = part_len
        if current_part:
            chunks.append(" ".join(current_part))
        return chunks

    # Step 3: Split by spaces (words)
    parts = text.split(" ")
    if len(parts) > 1:
        chunks = []
        current_part = []
        current_len = 0
        for part in parts:
            part_len = len(part.encode("utf-8"))
            if part_len > max_bytes:
                if current_part:
                    chunks.append(" ".join(current_part))
                    current_part = []
                    current_len = 0
                chunks.extend(split_message_text(part, max_bytes))
            else:
                sep_len = 1 if current_part else 0
                if current_len + sep_len + part_len <= max_bytes:
                    current_part.append(part)
                    current_len += sep_len + part_len
                else:
                    chunks.append(" ".join(current_part))
                    current_part = [part]
                    current_len = part_len
        if current_part:
            chunks.append(" ".join(current_part))
        return chunks

    # Step 4: Split by characters (slicing safely for UTF-8)
    chunks = []
    current_chars = []
    current_len = 0
    for char in text:
        char_len = len(char.encode("utf-8"))
        if current_len + char_len <= max_bytes:
            current_chars.append(char)
            current_len += char_len
        else:
            if current_chars:
                chunks.append("".join(current_chars))
            current_chars = [char]
            current_len = char_len
    if current_chars:
        chunks.append("".join(current_chars))
    return chunks


class UczelniaDaemon:
    """Orchestrates the lifecycle, polling, and AI interaction of the daemon."""

    def __init__(self, config: DaemonConfig) -> None:
        self.config = config
        self.start_time = time.time()
        self.session_message_count = 0

        # Validate that all required CLI/session parameters are present
        if (
            config.conversation_id is None
            or config.sesskey is None
            or config.cookie_name is None
            or config.cookie_value is None
            or config.user_id is None
        ):
            raise ValueError("Missing required configuration options")

        self.conversation_id: int = config.conversation_id
        self.sesskey: str = config.sesskey
        self.cookie_name: str = config.cookie_name
        self.cookie_value: str = config.cookie_value
        self.user_id: int = config.user_id

        # Resolve and ensure data directory exists
        self.data_dir = os.path.abspath(config.data_dir)
        os.makedirs(self.data_dir, exist_ok=True)

        # Initialize SQLite database in data directory
        db_path = os.path.join(self.data_dir, "messenger.db")
        self.db = DatabaseManager(db_path)

        # Re-sync user prompt configuration with Database
        db_prompt = self.db.get_active_prompt(self.conversation_id)
        if self.config.user_base_prompt:
            self.db.set_active_prompt(self.conversation_id, self.config.user_base_prompt)
        elif db_prompt:
            self.config.user_base_prompt = db_prompt

        # Initialize Moodle messenger client
        session_data = SessionData(
            sesskey=self.sesskey,
            cookies={self.cookie_name: self.cookie_value},
            user_id=self.user_id,
        )
        self.messenger_client = MessengerClient(session_data)

        # Create session record in database
        self.session_id = self.db.create_session(
            self.conversation_id, self.config.mode, self.config.model
        )

        # Initialize completions client depending on the engine setting
        if self.config.engine == "openai":
            self.ai_client = AIClient(
                base_url=self.config.ai_gateway["base_url"],
                api_key=self.config.ai_gateway["api_key"],
            )
        else:
            self.ai_client = HermesClient()

        # Initialize knowledge base
        self.knowledge_base = KnowledgeBase(self.config.knowledge_files)

        # State tracking
        self.processed_ids: Set[int] = set()
        self.shutdown_event = asyncio.Event()
        self.message_queue: asyncio.Queue[Any] = asyncio.Queue()

        # Initialize command handler
        self.command_handler = CommandHandler(
            config=self.config,
            db=self.db,
            conversation_id=self.conversation_id,
            get_uptime_seconds=self.get_uptime,
            get_message_count=self.get_message_count,
            clear_context_callback=self.clear_context,
            shutdown_callback=self.trigger_shutdown,
            get_knowledge_summary=self.knowledge_base.get_file_summary,
        )

        # Load system prompt relative to package structure (config/system_prompt.txt)
        sys_prompt_path = os.path.abspath(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "system_prompt.txt")
        )
        if os.path.exists(sys_prompt_path):
            with open(sys_prompt_path, "r", encoding="utf-8") as f:
                self.system_prompt_text = f.read()
        else:
            self.system_prompt_text = (
                "You are a direct, minimalist AI assistant connected to a university Moodle messenger chat. Respond concisely."
            )

        # Write initial status
        self.write_heartbeat("running", "startup")

    def write_heartbeat(self, status: str, last_event: str) -> None:
        """Writes current daemon status to daemon_status.json in the data directory."""
        status_path = os.path.join(self.data_dir, "daemon_status.json")
        try:
            uptime = self.get_uptime()
            msg_count = self.get_message_count()
            status_data = {
                "status": status,
                "pid": os.getpid(),
                "uptime_seconds": round(uptime, 1),
                "message_count": msg_count,
                "mode": self.config.mode,
                "model": self.config.model,
                "last_event": last_event,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=2)
            logger.info(f"Heartbeat updated: status={status}, event={last_event}")
        except Exception as e:
            logger.error(f"Failed to write heartbeat: {e}")

    def get_uptime(self) -> float:
        """Returns the daemon's uptime in seconds."""
        return time.time() - self.start_time

    def get_message_count(self) -> int:
        """Returns the number of messages processed in this session."""
        return self.session_message_count

    def clear_context(self) -> None:
        """Clears the history boundary by recreating the session in the DB."""
        now_str = datetime.now(timezone.utc).isoformat()
        self.db.close_session(self.session_id, cleaned_at=now_str)
        self.session_id = self.db.create_session(
            self.conversation_id, self.config.mode, self.config.model
        )
        logger.info(f"Context cleared. Started new session {self.session_id}")
        self.write_heartbeat("running", "context_cleared")

    def trigger_shutdown(self) -> None:
        """Triggers the shutdown event."""
        logger.info("Shutdown requested.")
        self.shutdown_event.set()

    def wrap_sentinels(self, text: str) -> str:
        """Strips existing sentinels and wraps the reply with AI markers."""
        cleaned = text.replace(self.config.sentinel_start, "").replace(
            self.config.sentinel_end, ""
        )
        return f"{self.config.sentinel_start}{cleaned}{self.config.sentinel_end}"

    async def send_response(self, text: str, role: str) -> None:
        """Splits, wraps, and sends a response to Moodle. Also logs to DB."""
        loop = asyncio.get_running_loop()
        chunks = split_message_text(text, max_bytes=3900)
        if not chunks:
            return

        for chunk in chunks:
            wrapped = self.wrap_sentinels(chunk)
            sent = await loop.run_in_executor(
                None,
                self.messenger_client.send_messages_to_conversation,
                self.conversation_id,
                wrapped,
            )
            sent_id = extract_message_id(sent)
            if sent_id:
                self.processed_ids.add(sent_id)
                self.db.insert_message(
                    self.session_id, sent_id, role, chunk, int(time.time())
                )
                self.session_message_count += 1
                logger.info(f"Sent response chunk (ID: {sent_id}, role: {role}).")
            else:
                logger.warning("Could not extract sent message ID from response.")

    async def initialize_session(self) -> None:
        """Seeds processed message IDs and sends the connection greeting."""
        loop = asyncio.get_running_loop()

        # Seed processed IDs from the last 20 messages to avoid processing historical chats
        try:
            msgs = await loop.run_in_executor(
                None,
                lambda: self.messenger_client.get_conversation_messages(
                    self.conversation_id, limit=20
                ),
            )
            for msg in msgs.messages:
                if msg.id is not None:
                    self.processed_ids.add(msg.id)
            logger.info(f"Seeded {len(self.processed_ids)} historical message IDs.")
        except Exception as e:
            logger.warning(f"Failed to seed message IDs: {e}. Starting fresh.")

        # Send connection notification
        try:
            await self.send_response("🤖 Connected", "system")
            logger.info("Sent daemon connected greeting.")
            self.write_heartbeat("running", "initialized")
        except Exception as e:
            logger.error(f"Failed to send initialization greeting: {e}", exc_info=True)

    async def handle_moodle_auth_error(self, error: Exception) -> None:
        """Attempts to re-authenticate using the login.py script."""
        err_msg = str(error).lower()
        if (
            "servicerequireslogin" in err_msg
            or "invalidsesskey" in err_msg
            or "invalid session" in err_msg
        ):
            logger.warning("Session key or cookie expired. Launching login.py subprocess...")

            refresh_path = os.path.join(self.data_dir, "session_refresh.json")
            if os.path.exists(refresh_path):
                try:
                    os.remove(refresh_path)
                except OSError:
                    pass

            login_script = os.path.abspath(
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "login", "login.py")
            )
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    login_script,
                    "--output",
                    refresh_path,
                    "--data-dir",
                    self.data_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=os.path.abspath(os.path.dirname(os.path.dirname(__file__))),
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode == 0 and os.path.exists(refresh_path):
                    with open(refresh_path, "r", encoding="utf-8") as f:
                        session_info = json.load(f)

                    # Update configuration cookies and key
                    self.config.sesskey = session_info["sesskey"]
                    self.config.cookie_value = session_info["cookies"].get(
                        self.config.cookie_name
                    ) or list(session_info["cookies"].values())[0]
                    self.sesskey = self.config.sesskey
                    self.cookie_value = self.config.cookie_value

                    # Reinitialize MessengerClient using correct class instantiation
                    new_session = SessionData(
                        sesskey=self.sesskey,
                        cookies={self.cookie_name: self.cookie_value},
                        user_id=self.user_id,
                    )
                    self.messenger_client = MessengerClient(new_session)

                    logger.info("Successfully re-authenticated and refreshed session.")
                    self.write_heartbeat("running", "reauthenticated")

                    try:
                        os.remove(refresh_path)
                    except OSError:
                        pass
                    return
                else:
                    error_detail = stderr.decode().strip() or "login.py failed"
                    logger.error(f"Re-authentication subprocess failed: {error_detail}")
            except Exception as e:
                logger.error(f"Failed executing re-auth: {e}", exc_info=True)
                error_detail = str(e)

            # Re-auth failed: write heartbeat and initiate shutdown
            self.write_heartbeat("auth_failed", f"login_failed: {error_detail}")
            logger.error("Authentication refresh failed. Disconnecting daemon.")
            self.shutdown_event.set()
        else:
            logger.error(f"Moodle API call failed: {error}", exc_info=True)

    async def run_poller(self) -> None:
        """Polls Moodle messenger for new messages."""
        loop = asyncio.get_running_loop()
        logger.info("Poller task started.")

        while not self.shutdown_event.is_set():
            try:
                # Fetch new messages
                messages_obj = await loop.run_in_executor(
                    None,
                    lambda: self.messenger_client.get_conversation_messages(
                        self.conversation_id, limit=50
                    ),
                )

                # Process polled messages chronologically (oldest first)
                for msg in reversed(messages_obj.messages):
                    if msg.id is None or msg.id in self.processed_ids:
                        continue

                    self.processed_ids.add(msg.id)

                    raw_text = msg.text or ""
                    # Strip HTML tags and unescape entities
                    text = html.unescape(re.sub(r'<.*?>', '', raw_text)).strip()

                    if is_command(text, self.config.command_prefix):
                        # Execute command inline
                        reply = self.command_handler.execute(text)
                        await self.send_response(reply, "system")

                        self.db.insert_message(
                            self.session_id,
                            msg.id,
                            "system",
                            text,
                            msg.time_created or int(time.time()),
                        )
                        self.session_message_count += 1
                        
                        # Heartbeat if command changed config
                        cmd_name, _ = parse_command(text, self.config.command_prefix)
                        if cmd_name in ("mode", "model", "clear", "prompt", "cleanup"):
                            self.write_heartbeat("running", f"command_{cmd_name}")
                    else:
                        # Queue user message for AI answer generation
                        self.db.insert_message(
                            self.session_id,
                            msg.id,
                            "user",
                            text,
                            msg.time_created or int(time.time()),
                        )
                        self.session_message_count += 1
                        await self.message_queue.put(msg)

            except MoodleAPIError as mae:
                await self.handle_moodle_auth_error(mae)
            except Exception as e:
                logger.error(f"Error in poller cycle: {e}", exc_info=True)

            # Wait for poll interval checking shutdown event in 1s increments
            for _ in range(int(self.config.poll_interval_seconds)):
                if self.shutdown_event.is_set():
                    break
                await asyncio.sleep(1)

        logger.info("Poller task stopped.")

    async def run_ai_worker(self) -> None:
        """Listens to queued user messages, aggregates batches, and requests completions."""
        logger.info("AI Worker task started.")

        while not self.shutdown_event.is_set():
            try:
                # Wait for at least one message to process
                try:
                    first_msg = await asyncio.wait_for(self.message_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                batch = [first_msg]
                # Drain rest of queue to aggregate back-to-back entries (natural batching)
                while not self.message_queue.empty():
                    try:
                        batch.append(self.message_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                batch_text = "\n".join(
                    html.unescape(re.sub(r'<.*?>', '', msg.text)).strip()
                    for msg in batch if msg.text
                )
                if not batch_text.strip():
                    continue

                # Retrieve history if in context mode
                history = None
                if self.config.mode == "context":
                    history = self.db.get_recent_messages(
                        self.conversation_id, self.config.max_history_turns
                    )

                # Search knowledge base if loaded
                knowledge_context = None
                if self.knowledge_base.chunks:
                    logger.info(f"Querying knowledge base for batch: '{batch_text[:50]}...'")
                    knowledge_context = self.knowledge_base.search(batch_text, top_k=3)

                logger.info(f"Generating AI completion for batch of {len(batch)} messages.")
                try:
                    reply = await self.ai_client.answer(
                        batch_text=batch_text,
                        history=history,
                        system_prompt=self.system_prompt_text,
                        user_prompt=self.config.user_base_prompt,
                        model=self.config.model,
                        knowledge_context=knowledge_context,
                    )
                except Exception as ae:
                    logger.error(f"AI gateway failed completely: {ae}")
                    reply = f"❌ AI Error: {ae}"

                await self.send_response(reply, "assistant")

            except Exception as e:
                logger.error(f"Error in AI worker loop: {e}", exc_info=True)

        logger.info("AI Worker task stopped.")

    async def shutdown(self) -> None:
        """Performs cleanup, sends farewell greeting, deletes session messages if required, and closes DB."""
        loop = asyncio.get_running_loop()
        logger.info("Initiating shutdown procedure...")

        # 1. Send disconnect greeting
        try:
            await self.send_response("🤖 Disconnected", "system")
        except Exception as e:
            logger.warning(f"Could not send disconnect farewell: {e}")

        # 2. Delete session messages if cleanup is enabled
        cleaned_at = None
        if self.config.cleanup_on_disconnect:
            logger.info("Cleanup on disconnect enabled. Deleting sent messages...")
            try:
                msg_ids = self.db.get_session_message_ids(self.session_id)
                for msg_id in msg_ids:
                    logger.info(f"Deleting message ID {msg_id} from Moodle...")
                    await loop.run_in_executor(
                        None, self.messenger_client.delete_message, msg_id
                    )
                cleaned_at = datetime.now(timezone.utc).isoformat()
                logger.info("Cleanup completed successfully.")
            except Exception as e:
                logger.error(f"Error during message cleanup: {e}", exc_info=True)

        # 3. Close SQLite Session & Database connection
        self.db.close_session(self.session_id, cleaned_at=cleaned_at)
        self.db.close()
        logger.info("Daemon shutdown completed.")
        
        # Write final status
        self.write_heartbeat("stopped", "shutdown")


async def main() -> None:
    # Load config and CLI arguments
    try:
        config = parse_args_and_load_config(sys.argv[1:])
    except Exception as e:
        sys.stderr.write(f"Failed parsing configuration: {e}\n")
        sys.exit(1)

    # Set up data directory and logging
    data_dir = os.path.abspath(config.data_dir)
    os.makedirs(data_dir, exist_ok=True)
    log_file = os.path.join(data_dir, "daemon.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.handlers.RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=3
            ),
        ],
    )

    # Validate required CLI/session variables
    required_vars = {
        "conversation-id": config.conversation_id,
        "sesskey": config.sesskey,
        "cookie-name": config.cookie_name,
        "cookie-value": config.cookie_value,
        "user-id": config.user_id,
    }
    missing = [name for name, val in required_vars.items() if val is None]
    if missing:
        logger.critical(
            f"Missing required parameters: {', '.join(missing)}. "
            "Please provide them via CLI arguments."
        )
        sys.exit(1)

    # Start the daemon
    daemon = UczelniaDaemon(config)
    await daemon.initialize_session()

    # Register signal handlers for SIGINT & SIGTERM
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, daemon.trigger_shutdown)

    # Launch Poller and Worker concurrently
    try:
        await asyncio.gather(
            daemon.run_poller(),
            daemon.run_ai_worker(),
        )
    finally:
        # Run cleanup on disconnect/shutdown
        await daemon.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
