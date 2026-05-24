import os
import tempfile
from typing import Generator
import pytest
from daemon.db import DatabaseManager


@pytest.fixture
def temp_db() -> Generator[DatabaseManager, None, None]:
    # Use temporary file database
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = DatabaseManager(path)
    yield db
    db.close()
    os.remove(path)


def test_session_lifecycle(temp_db: DatabaseManager) -> None:
    session_id = temp_db.create_session(conversation_id=123, mode="context", model="gpt-4")
    assert session_id == 1

    # Check session is active
    cursor = temp_db.conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    assert row["conversation_id"] == 123
    assert row["mode"] == "context"
    assert row["model"] == "gpt-4"
    assert row["ended_at"] is None
    assert row["cleaned_at"] is None

    # Close session
    temp_db.close_session(session_id, cleaned_at="2026-05-23T12:00:00")
    cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    assert row["ended_at"] is not None
    assert row["cleanup"] == 1
    assert row["cleaned_at"] == "2026-05-23T12:00:00"


def test_insert_and_get_messages(temp_db: DatabaseManager) -> None:
    session_id = temp_db.create_session(conversation_id=123, mode="context", model="gpt-4")

    # Insert some messages
    temp_db.insert_message(session_id, moodle_message_id=1, role="user", content="Hello", timestamp=1000)
    temp_db.insert_message(session_id, moodle_message_id=2, role="assistant", content="Hi there", timestamp=1001)
    temp_db.insert_message(session_id, moodle_message_id=3, role="system", content="Command", timestamp=1002)  # Should be ignored in history

    # Duplicate message ID should be ignored gracefully
    temp_db.insert_message(session_id, moodle_message_id=1, role="user", content="Hello duplicate", timestamp=1000)

    # Get messages
    msgs = temp_db.get_recent_messages(conversation_id=123, limit=10)
    assert len(msgs) == 2
    assert msgs[0] == {"role": "user", "content": "Hello"}
    assert msgs[1] == {"role": "assistant", "content": "Hi there"}


def test_get_recent_messages_filtering(temp_db: DatabaseManager) -> None:
    # Create two sessions for same conversation
    session_id_1 = temp_db.create_session(conversation_id=123, mode="context", model="gpt-4")
    temp_db.insert_message(session_id_1, moodle_message_id=1, role="user", content="Msg 1", timestamp=1000)

    session_id_2 = temp_db.create_session(conversation_id=123, mode="context", model="gpt-4")
    temp_db.insert_message(session_id_2, moodle_message_id=2, role="assistant", content="Msg 2", timestamp=1001)

    # All messages should be visible
    msgs = temp_db.get_recent_messages(conversation_id=123, limit=10)
    assert len(msgs) == 2

    # Clean the first session
    temp_db.update_session_cleaned(session_id_1, "2026-05-23T12:00:00")

    # Now Msg 1 (from session 1) should be filtered out because it is cleaned
    msgs_after_clean = temp_db.get_recent_messages(conversation_id=123, limit=10)
    assert len(msgs_after_clean) == 1
    assert msgs_after_clean[0]["content"] == "Msg 2"


def test_get_session_message_ids(temp_db: DatabaseManager) -> None:
    session_id = temp_db.create_session(conversation_id=123, mode="context", model="gpt-4")
    temp_db.insert_message(session_id, moodle_message_id=10, role="user", content="H", timestamp=100)
    temp_db.insert_message(session_id, moodle_message_id=20, role="assistant", content="O", timestamp=101)
    temp_db.insert_message(session_id, moodle_message_id=None, role="system", content="No Moodle ID", timestamp=102)

    ids = temp_db.get_session_message_ids(session_id)
    assert ids == [10, 20]


def test_prompt_operations(temp_db: DatabaseManager) -> None:
    # Initially no active prompt
    assert temp_db.get_active_prompt(conversation_id=123) is None

    # Set active prompt
    temp_db.set_active_prompt(conversation_id=123, prompt_text="Prompt V1")
    assert temp_db.get_active_prompt(conversation_id=123) == "Prompt V1"

    # Set new prompt (V1 is deactivated)
    temp_db.set_active_prompt(conversation_id=123, prompt_text="Prompt V2")
    assert temp_db.get_active_prompt(conversation_id=123) == "Prompt V2"

    # Undo prompt V2 -> V1
    reverted = temp_db.undo_active_prompt(conversation_id=123)
    assert reverted == "Prompt V1"
    assert temp_db.get_active_prompt(conversation_id=123) == "Prompt V1"

    # Undo again when there are no more history items
    assert temp_db.undo_active_prompt(conversation_id=123) is None

    # Deactivate prompts
    temp_db.deactivate_prompts(conversation_id=123)
    assert temp_db.get_active_prompt(conversation_id=123) is None
