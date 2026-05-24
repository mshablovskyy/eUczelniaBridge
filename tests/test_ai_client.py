from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from daemon.ai_client import AIClient


@pytest.mark.asyncio
async def test_ai_client_success() -> None:
    # Setup mock choices & response
    mock_choice = MagicMock()
    mock_choice.message.content = "Mocked AI Response"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("daemon.ai_client.AsyncOpenAI") as mock_openai_class:
        mock_instance = mock_openai_class.return_value
        mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)

        client = AIClient(base_url="http://fake", api_key="key")
        res = await client.answer(
            batch_text="Query Text",
            history=[
                {"role": "user", "content": "Prev User"},
                {"role": "assistant", "content": "Prev Assistant"},
            ],
            system_prompt="System instructions",
            user_prompt="User instructions",
            model="gpt-4o",
        )

        assert res == "Mocked AI Response"

        # Check call arguments
        mock_instance.chat.completions.create.assert_called_once_with(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "System instructions\n\nUser instructions for this session:\nUser instructions",
                },
                {"role": "user", "content": "Prev User"},
                {"role": "assistant", "content": "Prev Assistant"},
                {"role": "user", "content": "Query Text"},
            ],
            stream=False,
        )


@pytest.mark.asyncio
async def test_ai_client_knowledge_context() -> None:
    # Setup mock choices & response
    mock_choice = MagicMock()
    mock_choice.message.content = "Mocked Response With Context"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("daemon.ai_client.AsyncOpenAI") as mock_openai_class:
        mock_instance = mock_openai_class.return_value
        mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)

        client = AIClient(base_url="http://fake", api_key="key")
        res = await client.answer(
            batch_text="Query Text",
            history=None,
            system_prompt="System instructions",
            user_prompt="User instructions",
            model="gpt-4o",
            knowledge_context="This is a test knowledge document.",
        )

        assert res == "Mocked Response With Context"

        # Check call arguments includes knowledge_context
        mock_instance.chat.completions.create.assert_called_once_with(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "System instructions\n\nRelevant knowledge context:\nThis is a test knowledge document.\n\nUser instructions for this session:\nUser instructions",
                },
                {"role": "user", "content": "Query Text"},
            ],
            stream=False,
        )


@pytest.mark.asyncio
async def test_ai_client_retry_once() -> None:
    # Setup mock response
    mock_choice = MagicMock()
    mock_choice.message.content = "Succeeded on retry"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("daemon.ai_client.AsyncOpenAI") as mock_openai_class:
        mock_instance = mock_openai_class.return_value
        # First call raises Exception, second returns response
        mock_instance.chat.completions.create = AsyncMock(
            side_effect=[Exception("Transient Error"), mock_response]
        )

        client = AIClient(base_url="http://fake", api_key="key")
        res = await client.answer(
            batch_text="Query",
            history=None,
            system_prompt="Sys",
            user_prompt="",
            model="gpt-4o",
        )

        assert res == "Succeeded on retry"
        assert mock_instance.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_ai_client_failures_bubble() -> None:
    with patch("daemon.ai_client.AsyncOpenAI") as mock_openai_class:
        mock_instance = mock_openai_class.return_value
        # Both calls raise Exception
        mock_instance.chat.completions.create = AsyncMock(
            side_effect=[Exception("Error 1"), Exception("Error 2")]
        )

        client = AIClient(base_url="http://fake", api_key="key")

        with pytest.raises(Exception, match="Error 2"):
            await client.answer(
                batch_text="Query",
                history=None,
                system_prompt="Sys",
                user_prompt="",
                model="gpt-4o",
            )

        assert mock_instance.chat.completions.create.call_count == 2
