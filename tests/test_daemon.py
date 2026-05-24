import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch
import pytest
from daemon.config import DaemonConfig
from daemon.daemon import UczelniaDaemon, extract_message_id
from eUczelniaMessenger.models import SendResult


def test_extract_message_id() -> None:
    # 1. Simple dict
    assert extract_message_id(SendResult(raw={"id": 555})) == 555
    assert extract_message_id(SendResult(raw={"msgid": 666})) == 666

    # 2. List of dicts
    assert extract_message_id(SendResult(raw=[{"id": 123}])) == 123
    assert extract_message_id(SendResult(raw=[{"msgid": 456}])) == 456

    # 3. Nested messages key
    assert extract_message_id(SendResult(raw={"messages": [{"id": 789}]})) == 789

    # 4. Unknown format
    assert extract_message_id(SendResult(raw="unknown")) is None


@pytest.fixture
def base_config() -> DaemonConfig:
    config = DaemonConfig()
    config.conversation_id = 123
    config.sesskey = "sess"
    config.cookie_name = "cookie"
    config.cookie_value = "val"
    config.user_id = 999
    return config


@pytest.mark.asyncio
async def test_daemon_initialization_and_seeding(base_config: DaemonConfig) -> None:
    with patch("daemon.daemon.DatabaseManager") as mock_db_class, \
            patch("daemon.daemon.MessengerClient") as mock_client_class, \
            patch("daemon.daemon.AIClient"), \
            patch("daemon.daemon.KnowledgeBase") as mock_kb_class:

        mock_db = mock_db_class.return_value
        mock_db.get_active_prompt.return_value = None
        mock_db.create_session.return_value = 42

        mock_client = mock_client_class.return_value
        # Mock historical messages
        mock_msg_1 = MagicMock()
        mock_msg_1.id = 1001
        mock_msg_2 = MagicMock()
        mock_msg_2.id = 1002
        mock_messages = MagicMock()
        mock_messages.messages = [mock_msg_1, mock_msg_2]
        mock_client.get_conversation_messages.return_value = mock_messages

        # Mock sent message for Connected greeting
        mock_client.send_messages_to_conversation.return_value = SendResult(raw={"id": 2001})

        daemon = UczelniaDaemon(base_config)
        await daemon.initialize_session()

        # Check session creation and history seeding
        mock_db.create_session.assert_called_once_with(123, "stateless", "gpt-4o-mini")
        assert 1001 in daemon.processed_ids
        assert 1002 in daemon.processed_ids
        assert 2001 in daemon.processed_ids

        # Check connect greeting was sent and logged
        mock_client.send_messages_to_conversation.assert_called_once_with(123, "«AI»🤖 Connected«/AI»")
        mock_db.insert_message.assert_called_once_with(42, 2001, "system", "🤖 Connected", ANY)


@pytest.mark.asyncio
async def test_daemon_poller_regular_message_and_command(base_config: DaemonConfig) -> None:
    with patch("daemon.daemon.DatabaseManager") as mock_db_class, \
            patch("daemon.daemon.MessengerClient") as mock_client_class, \
            patch("daemon.daemon.AIClient"), \
            patch("daemon.daemon.KnowledgeBase"):

        mock_db = mock_db_class.return_value
        mock_db.create_session.return_value = 42
        mock_client = mock_client_class.return_value

        # Mock polled messages: one regular user query, one command, and one AI response (sentinel)
        m1 = MagicMock()
        m1.id = 5001
        m1.text = "Hello AI"
        m1.time_created = 1000
        m1.useridfrom = 111

        m2 = MagicMock()
        m2.id = 5002
        m2.text = "!status"
        m2.time_created = 1001
        m2.useridfrom = 111

        m3 = MagicMock()
        m3.id = 5003
        m3.text = "«AI»🤖 Connected«/AI»"
        m3.time_created = 1002
        m3.useridfrom = 999  # Sent by daemon

        polled_messages = MagicMock()
        polled_messages.messages = [m3, m2, m1]  # Newest first, so reversed will process m1 then m2 then m3
        mock_client.get_conversation_messages.return_value = polled_messages

        # Command response send mock
        mock_client.send_messages_to_conversation.return_value = SendResult(raw={"id": 6002})

        daemon = UczelniaDaemon(base_config)
        # Seed processed_ids with m3's id to simulate a message sent by the daemon
        daemon.processed_ids = {5003}

        # Run poller cycle (allow one cycle to execute, then signal shutdown)
        task = asyncio.create_task(daemon.run_poller())
        await asyncio.sleep(0.05)
        daemon.shutdown_event.set()
        await task

        # Regular message m1: should be in queue and inserted into DB as 'user'
        assert daemon.message_queue.qsize() == 1
        queued = await daemon.message_queue.get()
        assert queued.id == 5001
        mock_db.insert_message.assert_any_call(42, 5001, "user", "Hello AI", 1000)

        # Command m2: should execute immediately (status command response)
        # Should be sent to moodle and logged in DB as 'system'
        mock_client.send_messages_to_conversation.assert_any_call(123, ANY)
        mock_db.insert_message.assert_any_call(42, 5002, "system", "!status", 1001)
        mock_db.insert_message.assert_any_call(42, 6002, "system", ANY, ANY)

        # Sentinel message m3: should be ignored, but added to processed_ids
        assert 5003 in daemon.processed_ids


@pytest.mark.asyncio
async def test_daemon_ai_worker_batching(base_config: DaemonConfig) -> None:
    with patch("daemon.daemon.DatabaseManager") as mock_db_class, \
            patch("daemon.daemon.MessengerClient") as mock_client_class, \
            patch("daemon.daemon.AIClient") as mock_ai_class, \
            patch("daemon.daemon.KnowledgeBase") as mock_kb_class:

        mock_db = mock_db_class.return_value
        mock_db.create_session.return_value = 42
        mock_client = mock_client_class.return_value

        mock_kb = mock_kb_class.return_value
        mock_kb.chunks = []

        mock_ai = mock_ai_class.return_value
        mock_ai.answer = AsyncMock(return_value="AI answer text")

        mock_client.send_messages_to_conversation.return_value = SendResult(raw={"id": 8001})

        daemon = UczelniaDaemon(base_config)
        daemon.config.mode = "context"
        daemon.system_prompt_text = "Sys Prompt"
        daemon.config.user_base_prompt = "User prompt V1"

        # Queue multiple messages to simulate batching
        msg_a = MagicMock()
        msg_a.text = "Tell me"
        msg_b = MagicMock()
        msg_b.text = "about python"
        await daemon.message_queue.put(msg_a)
        await daemon.message_queue.put(msg_b)

        # Let the loop run (allow one cycle to execute, then signal shutdown)
        task = asyncio.create_task(daemon.run_ai_worker())
        await asyncio.sleep(0.05)
        daemon.shutdown_event.set()
        await task

        # Check that both messages were batched and answer() called with concatenated string
        mock_ai.answer.assert_called_once_with(
            batch_text="Tell me\nabout python",
            history=ANY,
            system_prompt="Sys Prompt",
            user_prompt="User prompt V1",
            model="gpt-4o-mini",
            knowledge_context=None,
        )

        # Verify sent message wrapped with sentinels
        mock_client.send_messages_to_conversation.assert_called_once_with(123, "«AI»AI answer text«/AI»")
        # Verify response logged in DB as 'assistant'
        mock_db.insert_message.assert_called_once_with(42, 8001, "assistant", "AI answer text", ANY)


@pytest.mark.asyncio
async def test_daemon_shutdown_and_cleanup(base_config: DaemonConfig) -> None:
    with patch("daemon.daemon.DatabaseManager") as mock_db_class, \
            patch("daemon.daemon.MessengerClient") as mock_client_class, \
            patch("daemon.daemon.AIClient"), \
            patch("daemon.daemon.KnowledgeBase"):

        mock_db = mock_db_class.return_value
        mock_db.create_session.return_value = 42
        mock_client = mock_client_class.return_value

        # Mock sent message for Disconnected greeting
        mock_client.send_messages_to_conversation.return_value = SendResult(raw={"id": 9001})
        # Mock session message IDs to delete
        mock_db.get_session_message_ids.return_value = [11, 22]

        # Case 1: Cleanup enabled
        base_config.cleanup_on_disconnect = True
        daemon = UczelniaDaemon(base_config)
        await daemon.shutdown()

        # Verify disconnected greeting sent
        mock_client.send_messages_to_conversation.assert_called_once_with(123, "«AI»🤖 Disconnected«/AI»")
        # Verify message deletion calls
        mock_client.delete_message.assert_any_call(11)
        mock_client.delete_message.assert_any_call(22)
        # Verify close_session logs cleanup timestamp
        mock_db.close_session.assert_called_once_with(42, cleaned_at=ANY)


def test_split_message_text() -> None:
    from daemon.daemon import split_message_text

    # 1. Short text fits in limit
    assert split_message_text("hello world", 100) == ["hello world"]

    # 2. Split by paragraph (newline)
    text = "para1\npara2\npara3"
    assert split_message_text(text, 10) == ["para1", "para2", "para3"]
    assert split_message_text(text, 12) == ["para1\npara2", "para3"]

    # 3. Split by sentence
    text_sentence = "Sentence one. Sentence two! Sentence three?"
    # Max bytes 15: "Sentence one." (13 bytes), "Sentence two!" (13 bytes), "Sentence three?" (15 bytes)
    assert split_message_text(text_sentence, 15) == ["Sentence one.", "Sentence two!", "Sentence three?"]

    # 4. Split by words
    text_words = "word1 word2 word3"
    assert split_message_text(text_words, 6) == ["word1", "word2", "word3"]
    assert split_message_text(text_words, 11) == ["word1 word2", "word3"]

    # 5. Split by characters (extremely long word)
    text_long_word = "abcdef"
    assert split_message_text(text_long_word, 2) == ["ab", "cd", "ef"]

    # 6. UTF-8 multi-byte correctness
    # "zażółć gęślą jaźń" (26 bytes)
    utf8_text = "zażółć gęślą jaźń"
    chunks = split_message_text(utf8_text, 10)
    for c in chunks:
        assert len(c.encode("utf-8")) <= 10
    assert chunks == ["zażółć", "gęślą", "jaźń"]


@pytest.mark.asyncio
async def test_daemon_send_response_splitting(base_config: DaemonConfig) -> None:
    with patch("daemon.daemon.DatabaseManager") as mock_db_class, \
            patch("daemon.daemon.MessengerClient") as mock_client_class, \
            patch("daemon.daemon.AIClient"), \
            patch("daemon.daemon.KnowledgeBase"):

        mock_db = mock_db_class.return_value
        mock_db.create_session.return_value = 42
        mock_client = mock_client_class.return_value

        # Mock send calls
        mock_client.send_messages_to_conversation.side_effect = [
            SendResult(raw={"id": 7001}),
            SendResult(raw={"id": 7002}),
        ]

        daemon = UczelniaDaemon(base_config)
        # Mock split_message_text to return two chunks
        with patch("daemon.daemon.split_message_text", return_value=["part1", "part2"]) as mock_split:
            await daemon.send_response("full response", "assistant")

            mock_split.assert_called_once_with("full response", max_bytes=3900)
            assert mock_client.send_messages_to_conversation.call_count == 2
            mock_client.send_messages_to_conversation.assert_any_call(123, "«AI»part1«/AI»")
            mock_client.send_messages_to_conversation.assert_any_call(123, "«AI»part2«/AI»")

            assert 7001 in daemon.processed_ids
            assert 7002 in daemon.processed_ids
            assert daemon.session_message_count == 2

            mock_db.insert_message.assert_any_call(42, 7001, "assistant", "part1", ANY)
            mock_db.insert_message.assert_any_call(42, 7002, "assistant", "part2", ANY)
