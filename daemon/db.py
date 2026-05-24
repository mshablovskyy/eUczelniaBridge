import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class DatabaseManager:
    """Manages the SQLite database for session and chat history tracking.

    Implements schema creation, session management, message logging,
    and prompt history persistence.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Creates the schema tables if they do not exist."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id  INTEGER NOT NULL,
                started_at       TEXT NOT NULL,
                ended_at         TEXT,
                mode             TEXT NOT NULL,
                model            TEXT,
                cleanup          INTEGER DEFAULT 0,
                cleaned_at       TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id        INTEGER NOT NULL REFERENCES sessions(id),
                moodle_message_id INTEGER,
                role              TEXT NOT NULL,
                content           TEXT NOT NULL,
                timestamp         INTEGER NOT NULL,
                UNIQUE(moodle_message_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_prompts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id  INTEGER NOT NULL,
                prompt_text      TEXT NOT NULL,
                created_at       TEXT NOT NULL,
                is_active        INTEGER DEFAULT 0
            )
            """
        )
        self.conn.commit()

    def create_session(self, conversation_id: int, mode: str, model: str) -> int:
        """Creates a new session record.

        Args:
            conversation_id: The monitored conversation ID.
            mode: Operating mode ('stateless' or 'context').
            model: The AI model used.

        Returns:
            The newly created session's ID.
        """
        cursor = self.conn.cursor()
        started_at = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "INSERT INTO sessions (conversation_id, started_at, mode, model) VALUES (?, ?, ?, ?)",
            (conversation_id, started_at, mode, model),
        )
        self.conn.commit()
        rowid = cursor.lastrowid
        return int(rowid) if rowid is not None else 0

    def close_session(self, session_id: int, cleaned_at: Optional[str] = None) -> None:
        """Closes a session, recording the ended time and cleanup status.

        Args:
            session_id: The ID of the session to close.
            cleaned_at: Optional timestamp if cleanup was executed.
        """
        cursor = self.conn.cursor()
        ended_at = datetime.now(timezone.utc).isoformat()
        if cleaned_at:
            cursor.execute(
                "UPDATE sessions SET ended_at = ?, cleanup = 1, cleaned_at = ? WHERE id = ?",
                (ended_at, cleaned_at, session_id),
            )
        else:
            cursor.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?",
                (ended_at, session_id),
            )
        self.conn.commit()

    def update_session_cleaned(self, session_id: int, cleaned_at: str) -> None:
        """Updates session cleanup information mid-session or on disconnect.

        Args:
            session_id: The session ID.
            cleaned_at: Timestamp when cleanup was run.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE sessions SET cleanup = 1, cleaned_at = ? WHERE id = ?",
            (cleaned_at, session_id),
        )
        self.conn.commit()

    def insert_message(
        self,
        session_id: int,
        moodle_message_id: Optional[int],
        role: str,
        content: str,
        timestamp: int,
    ) -> None:
        """Inserts a message log.

        Args:
            session_id: Session ID the message belongs to.
            moodle_message_id: Unique message ID from Moodle.
            role: Sender role ('user', 'assistant', or 'system').
            content: The text contents.
            timestamp: Unix timestamp.
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO messages (session_id, moodle_message_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
                (session_id, moodle_message_id, role, content, timestamp),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            # Handle duplicate Moodle message IDs gracefully (ignore or update)
            pass

    def get_recent_messages(self, conversation_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieves messages for context mode from non-cleaned sessions.

        Args:
            conversation_id: Monitored conversation ID.
            limit: Maximum messages to retrieve.

        Returns:
            A list of messages (chronological order) containing role and content.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT m.role, m.content
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            WHERE s.conversation_id = ?
              AND s.cleaned_at IS NULL
              AND m.role IN ('user', 'assistant')
            ORDER BY m.timestamp DESC, m.id DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        rows = cursor.fetchall()
        messages = [{"role": row["role"], "content": row["content"]} for row in rows]
        messages.reverse()
        return messages

    def get_session_message_ids(self, session_id: int) -> List[int]:
        """Gets all moodle message IDs associated with a session.

        Args:
            session_id: The session ID.

        Returns:
            A list of Moodle message IDs.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT moodle_message_id FROM messages WHERE session_id = ? AND moodle_message_id IS NOT NULL",
            (session_id,),
        )
        return [int(row["moodle_message_id"]) for row in cursor.fetchall()]

    def get_active_prompt(self, conversation_id: int) -> Optional[str]:
        """Gets the currently active base prompt for a conversation.

        Args:
            conversation_id: The conversation ID.

        Returns:
            The active prompt text, or None.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT prompt_text FROM user_prompts WHERE conversation_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        )
        row = cursor.fetchone()
        return str(row["prompt_text"]) if row else None

    def set_active_prompt(self, conversation_id: int, prompt_text: str) -> None:
        """Sets the active base prompt, deactivating previous ones.

        Args:
            conversation_id: The conversation ID.
            prompt_text: The new base prompt text.
        """
        cursor = self.conn.cursor()
        created_at = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "UPDATE user_prompts SET is_active = 0 WHERE conversation_id = ?",
            (conversation_id,),
        )
        cursor.execute(
            "INSERT INTO user_prompts (conversation_id, prompt_text, created_at, is_active) VALUES (?, ?, ?, 1)",
            (conversation_id, prompt_text, created_at),
        )
        self.conn.commit()

    def deactivate_prompts(self, conversation_id: int) -> None:
        """Deactivates all prompts for a conversation.

        Args:
            conversation_id: The conversation ID.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE user_prompts SET is_active = 0 WHERE conversation_id = ?",
            (conversation_id,),
        )
        self.conn.commit()

    def undo_active_prompt(self, conversation_id: int) -> Optional[str]:
        """Reverts to the second most recent prompt.

        Deletes the current active prompt and sets the new latest prompt to active.

        Args:
            conversation_id: The conversation ID.

        Returns:
            The reverted prompt text if successful, or None.
        """
        cursor = self.conn.cursor()
        # Find the active prompt id
        cursor.execute(
            "SELECT id FROM user_prompts WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        # Delete the latest prompt
        cursor.execute("DELETE FROM user_prompts WHERE id = ?", (row["id"],))

        # Retrieve the new latest prompt (which will become the active one)
        cursor.execute(
            "SELECT id, prompt_text FROM user_prompts WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        )
        new_row = cursor.fetchone()
        if new_row:
            cursor.execute(
                "UPDATE user_prompts SET is_active = 0 WHERE conversation_id = ?",
                (conversation_id,),
            )
            cursor.execute(
                "UPDATE user_prompts SET is_active = 1 WHERE id = ?",
                (new_row["id"],),
            )
            self.conn.commit()
            return str(new_row["prompt_text"])
        else:
            self.conn.commit()
            return None

    def close(self) -> None:
        """Closes the connection to the database."""
        self.conn.close()
