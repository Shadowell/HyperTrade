"""DeepSeek OpenAI-compatible chat client."""

from hypertrade.providers.chat import (
    ChatResponse,
    OpenAICompatibleChatProvider,
    ToolCallRequest,
)


class DeepSeekClient(OpenAICompatibleChatProvider):
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        super().__init__(name="deepseek", api_key=api_key, base_url=base_url, model=model)


__all__ = ["ChatResponse", "DeepSeekClient", "ToolCallRequest"]
