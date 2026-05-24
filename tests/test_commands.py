from unittest.mock import MagicMock
import pytest
from daemon.commands import CommandHandler, is_command, parse_command
from daemon.config import DaemonConfig


def test_command_detection_and_parsing() -> None:
    assert is_command("!help", "!") is True
    assert is_command("help", "!") is False
    assert is_command("  !status  ", "!") is True

    cmd, args = parse_command("!prompt set hello world", "!")
    assert cmd == "prompt"
    assert args == "set hello world"

    cmd, args = parse_command("!help", "!")
    assert cmd == "help"
    assert args == ""

    cmd, args = parse_command("!", "!")
    assert cmd == ""
    assert args == ""


@pytest.fixture
def mock_handler() -> tuple[CommandHandler, DaemonConfig, MagicMock]:
    config = DaemonConfig()
    db = MagicMock()
    # Mock callbacks
    get_uptime = MagicMock(return_value=3665.0)  # 1h 1m 5s
    get_msg_count = MagicMock(return_value=12)
    clear_cb = MagicMock()
    shutdown_cb = MagicMock()
    get_knowledge_summary = MagicMock(return_value="Loaded knowledge files:\n- doc.md (3 chunks)")

    handler = CommandHandler(
        config=config,
        db=db,
        conversation_id=123,
        get_uptime_seconds=get_uptime,
        get_message_count=get_msg_count,
        clear_context_callback=clear_cb,
        shutdown_callback=shutdown_cb,
        get_knowledge_summary=get_knowledge_summary,
    )
    return handler, config, db


def test_help_command(mock_handler: tuple[CommandHandler, DaemonConfig, MagicMock]) -> None:
    handler, config, _ = mock_handler
    res = handler.execute("!help")
    assert "Available commands" in res
    assert f"- {config.command_prefix}status" in res
    assert f"- {config.command_prefix}knowledge show" in res


def test_status_command(mock_handler: tuple[CommandHandler, DaemonConfig, MagicMock]) -> None:
    handler, config, _ = mock_handler
    res = handler.execute("!status")
    assert "Status:" in res
    assert "Mode: stateless" in res
    assert "Uptime: 1h 1m 5s" in res
    assert "Messages in session: 12" in res


def test_mode_command(mock_handler: tuple[CommandHandler, DaemonConfig, MagicMock]) -> None:
    handler, config, _ = mock_handler

    # Test switch to context
    res = handler.execute("!mode context")
    assert "Mode switched to context" in res
    assert config.mode == "context"

    # Test switch to stateless
    res = handler.execute("!mode stateless")
    assert "Mode switched to stateless" in res
    assert config.mode == "stateless"

    # Invalid mode
    res = handler.execute("!mode invalid")
    assert "Invalid mode" in res


def test_clear_command(mock_handler: tuple[CommandHandler, DaemonConfig, MagicMock]) -> None:
    handler, config, _ = mock_handler
    clear_cb = handler.clear_context_callback
    assert isinstance(clear_cb, MagicMock)

    # Clear is not available in stateless mode
    config.mode = "stateless"
    res = handler.execute("!clear")
    assert "only available in context mode" in res
    clear_cb.assert_not_called()

    # Clear in context mode
    config.mode = "context"
    res = handler.execute("!clear")
    assert "Context history cleared" in res
    clear_cb.assert_called_once()


def test_model_command(mock_handler: tuple[CommandHandler, DaemonConfig, MagicMock]) -> None:
    handler, config, _ = mock_handler
    res = handler.execute("!model gpt-4-turbo")
    assert "Model changed to gpt-4-turbo" in res
    assert config.model == "gpt-4-turbo"

    res = handler.execute("!model   ")
    assert "Model name cannot be empty" in res


def test_cleanup_command(mock_handler: tuple[CommandHandler, DaemonConfig, MagicMock]) -> None:
    handler, config, _ = mock_handler

    res = handler.execute("!cleanup on")
    assert "cleanup on disconnect enabled" in res
    assert config.cleanup_on_disconnect is True

    res = handler.execute("!cleanup off")
    assert "cleanup on disconnect disabled" in res
    assert config.cleanup_on_disconnect is False

    res = handler.execute("!cleanup invalid")
    assert "Invalid option" in res


def test_prompt_commands(mock_handler: tuple[CommandHandler, DaemonConfig, MagicMock]) -> None:
    handler, config, db = mock_handler

    # show empty
    res = handler.execute("!prompt show")
    assert "No base prompt is currently set" in res

    # set prompt
    res = handler.execute("!prompt set Be polite")
    assert "Base prompt set" in res
    assert config.user_base_prompt == "Be polite"
    db.set_active_prompt.assert_called_once_with(123, "Be polite")
    db.set_active_prompt.reset_mock()

    # append prompt
    res = handler.execute("!prompt append Speak Shakespearean")
    assert "Base prompt updated" in res
    assert config.user_base_prompt == "Be polite\nSpeak Shakespearean"
    db.set_active_prompt.assert_called_once_with(123, "Be polite\nSpeak Shakespearean")
    db.set_active_prompt.reset_mock()

    # show prompt
    res = handler.execute("!prompt show")
    assert "Current base prompt:" in res
    assert "Shakespearean" in res

    # undo prompt (db returns reverted prompt)
    db.undo_active_prompt.return_value = "Be polite"
    res = handler.execute("!prompt undo")
    assert "reverted to: Be polite" in res
    assert config.user_base_prompt == "Be polite"
    db.undo_active_prompt.assert_called_once_with(123)
    db.undo_active_prompt.reset_mock()

    # undo prompt to empty (db returns None)
    db.undo_active_prompt.return_value = None
    res = handler.execute("!prompt undo")
    assert "prompt cleared" in res
    assert config.user_base_prompt == ""


def test_knowledge_command(mock_handler: tuple[CommandHandler, DaemonConfig, MagicMock]) -> None:
    handler, _, _ = mock_handler

    res = handler.execute("!knowledge show")
    assert "Loaded knowledge files" in res
    assert "doc.md" in res


def test_disconnect_command(mock_handler: tuple[CommandHandler, DaemonConfig, MagicMock]) -> None:
    handler, _, _ = mock_handler
    shutdown_cb = handler.shutdown_callback
    assert isinstance(shutdown_cb, MagicMock)

    res = handler.execute("!disconnect")
    assert "Disconnecting..." in res
    shutdown_cb.assert_called_once()
