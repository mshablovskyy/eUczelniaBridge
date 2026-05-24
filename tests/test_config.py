import json
import os
import tempfile
from daemon.config import DaemonConfig, parse_args_and_load_config


def test_default_config() -> None:
    config = DaemonConfig()
    assert config.poll_interval_seconds == 12.0
    assert config.mode == "stateless"
    assert config.max_history_turns == 20
    assert config.cleanup_on_disconnect is False
    assert config.command_prefix == "!"
    assert config.sentinel_start == "«AI»"
    assert config.sentinel_end == "«/AI»"
    assert config.model == "gpt-4o-mini"
    assert config.conversation_id is None
    assert config.user_base_prompt == ""
    assert config.data_dir == "./data"
    assert config.knowledge_files == []


def test_load_from_json() -> None:
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
        json.dump(
            {
                "poll_interval_seconds": 5.5,
                "mode": "context",
                "max_history_turns": 10,
                "cleanup_on_disconnect": True,
                "command_prefix": "?",
                "sentinel_start": "START",
                "sentinel_end": "END",
                "data_dir": "./custom_data",
                "knowledge_files": ["doc1.md", "doc2.txt"],
                "ai_gateway": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "secret",
                    "model": "gpt-4o",
                },
            },
            f,
        )
        f.flush()
        temp_path = f.name

    try:
        config = DaemonConfig()
        config.load_from_json(temp_path)

        assert config.poll_interval_seconds == 5.5
        assert config.mode == "context"
        assert config.max_history_turns == 10
        assert config.cleanup_on_disconnect is True
        assert config.command_prefix == "?"
        assert config.sentinel_start == "START"
        assert config.sentinel_end == "END"
        assert config.data_dir == "./custom_data"
        assert config.knowledge_files == ["doc1.md", "doc2.txt"]
        assert config.ai_gateway["base_url"] == "https://api.openai.com/v1"
        assert config.ai_gateway["api_key"] == "secret"
        assert config.model == "gpt-4o"
    finally:
        os.remove(temp_path)


def test_cli_overrides() -> None:
    argv = [
        "--conversation-id",
        "123",
        "--sesskey",
        "keysess",
        "--cookie-name",
        "MoodleCookie",
        "--cookie-value",
        "cookieval",
        "--user-id",
        "999",
        "--user-prompt",
        "Test Prompt",
        "--data-dir",
        "./cli_data",
        "--knowledge-file",
        "file1.txt",
        "--knowledge-file",
        "file2.md",
    ]
    config = parse_args_and_load_config(argv)

    assert config.conversation_id == 123
    assert config.sesskey == "keysess"
    assert config.cookie_name == "MoodleCookie"
    assert config.cookie_value == "cookieval"
    assert config.user_id == 999
    assert config.user_base_prompt == "Test Prompt"
    assert config.data_dir == "./cli_data"
    assert config.knowledge_files == ["file1.txt", "file2.md"]


def test_prompt_mutability() -> None:
    config = DaemonConfig()
    config.set_user_prompt("Original Prompt")
    assert config.user_base_prompt == "Original Prompt"

    config.append_user_prompt("Appended Prompt")
    assert config.user_base_prompt == "Original Prompt\nAppended Prompt"

    undone = config.undo_user_prompt()
    assert undone is True
    assert config.user_base_prompt == "Original Prompt"

    undone_again = config.undo_user_prompt()
    assert undone_again is False
    assert config.user_base_prompt == "Original Prompt"
