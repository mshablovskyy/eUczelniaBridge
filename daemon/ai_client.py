import logging
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class AIClient:
    """Async wrapper around the OpenAI SDK client for chat completions."""

    def __init__(self, base_url: str, api_key: str) -> None:
        """Initializes the AsyncOpenAI client.

        Args:
            base_url: The base URL for the API endpoint.
            api_key: The API key.
        """
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def answer(
        self,
        batch_text: str,
        history: Optional[List[Dict[str, Any]]],
        system_prompt: str,
        user_prompt: str,
        model: str,
        knowledge_context: Optional[str] = None,
    ) -> str:
        """Prepares a multi-turn chat payload and requests completion.

        Retries once on any exception before bubbling the error up.

        Args:
            batch_text: Concatenated user queries from the current batch.
            history: Optional list of past messages in the conversation.
            system_prompt: Core system prompt instruction string.
            user_prompt: Base user instruction/prompt override.
            model: The AI model to use for completion.
            knowledge_context: Optional context retrieved from the knowledge base.

        Returns:
            The completion answer from the AI model.
        """
        # Build the system instruction
        full_system_prompt = system_prompt
        
        if knowledge_context:
            full_system_prompt += f"\n\nRelevant knowledge context:\n{knowledge_context}"
            
        if user_prompt:
            full_system_prompt += f"\n\nUser instructions for this session:\n{user_prompt}"

        messages = [{"role": "system", "content": full_system_prompt}]

        # Inject chat history if present
        if history:
            for message in history:
                messages.append({"role": message["role"], "content": message["content"]})

        # Append current batch user prompt
        messages.append({"role": "user", "content": batch_text})

        # Execute completion request with retry once
        try:
            return await self._request_completion(model, messages)
        except Exception as e:
            logger.warning(
                f"First completion attempt failed with error: {e}. Retrying once..."
            )
            # Second attempt (letting exception bubble if this fails as well)
            return await self._request_completion(model, messages)

    async def _request_completion(self, model: str, messages: List[Dict[str, Any]]) -> str:
        """Sends the request to the completion endpoint."""
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            stream=False,
        )
        content = response.choices[0].message.content  # type: ignore[union-attr]
        return content if content is not None else ""
