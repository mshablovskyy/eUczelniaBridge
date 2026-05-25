import os
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from daemon.hermes_client import HermesClient


@pytest.mark.asyncio
async def test_hermes_client_success() -> None:
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"Hermes Final Output", b""))
    mock_proc.returncode = 0

    with patch("daemon.hermes_client.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec, \
         patch("daemon.hermes_client.shutil.which", return_value="/usr/local/bin/hermes"):

        client = HermesClient()
        res = await client.answer(
            batch_text="Polled query text",
            history=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ],
            system_prompt="Be a tutor.",
            user_prompt="Explain programming.",
            model="gpt-4o",
            knowledge_context="Python is easy.",
        )

        assert res == "Hermes Final Output"
        mock_exec.assert_called_once()
        args, kwargs = mock_exec.call_args
        
        # Verify binary executable
        assert args[0] == "/usr/local/bin/hermes"
        assert args[1] == "chat"
        assert args[2] == "-q"
        
        # Verify query serialization structure
        query = args[3]
        assert "Be a tutor." in query
        assert "Relevant knowledge context:\nPython is easy." in query
        assert "User instructions for this session:\nExplain programming." in query
        assert "Conversation history:" in query
        assert "<user>: Hello" in query
        assert "<assistant>: Hi there" in query
        assert "New message from the chat:\nPolled query text" in query

        # Verify yolo and quiet mode flags
        assert args[4] == "--yolo"
        assert args[5] == "-Q"


@pytest.mark.asyncio
async def test_hermes_client_timeout() -> None:
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_proc.kill = MagicMock()

    with patch("daemon.hermes_client.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec, \
         patch("daemon.hermes_client.shutil.which", return_value="/usr/local/bin/hermes"):

        client = HermesClient()
        with pytest.raises(RuntimeError, match="timed out"):
            await client.answer(
                batch_text="Query",
                history=None,
                system_prompt="Sys",
                user_prompt="",
                model="gpt-4o",
            )
        assert mock_exec.call_count == 2
        assert mock_proc.kill.call_count == 2


@pytest.mark.asyncio
async def test_hermes_client_exit_code_error() -> None:
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.returncode = 1  # Error exit code

    with patch("daemon.hermes_client.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec, \
         patch("daemon.hermes_client.shutil.which", return_value="/usr/local/bin/hermes"):

        client = HermesClient()
        # Retries once, so it fails twice
        with pytest.raises(RuntimeError, match="failed with exit code: 1"):
            await client.answer(
                batch_text="Query",
                history=None,
                system_prompt="Sys",
                user_prompt="",
                model="gpt-4o",
            )
        
        assert mock_exec.call_count == 2


def test_hermes_client_binary_resolution() -> None:
    # Test env var priority
    with patch.dict(os.environ, {"HERMES_BIN": "/custom/path/hermes"}), \
         patch("daemon.hermes_client.os.path.exists", return_value=True):
        client = HermesClient()
        assert client._resolve_hermes_path() == "/custom/path/hermes"

    # Test PATH lookup priority when env var file doesn't exist
    with patch.dict(os.environ, {"HERMES_BIN": "/custom/path/hermes"}), \
         patch("daemon.hermes_client.os.path.exists", side_effect=lambda p: p != "/custom/path/hermes"), \
         patch("daemon.hermes_client.shutil.which", return_value="/system/bin/hermes"):
        client = HermesClient()
        assert client._resolve_hermes_path() == "/system/bin/hermes"

    # Test standard home venv search paths
    with patch.dict(os.environ, {}), \
         patch("daemon.hermes_client.shutil.which", return_value=None), \
         patch("daemon.hermes_client.os.path.exists", side_effect=lambda p: ".hermes" in p):
        client = HermesClient()
        assert ".hermes" in client._resolve_hermes_path()
