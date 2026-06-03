"""Runtime provider router.

ProviderRuntime is the single place that turns environment configuration into a
chat provider. It never exposes API keys in status payloads; API, CLI, and the
frontend only see provider names, model names, and key status.
"""

from dataclasses import dataclass

from hypertrade.config import Settings
from hypertrade.providers.chat import ChatProvider, OpenAICompatibleChatProvider
from hypertrade.providers.deepseek import DeepSeekClient


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    display_name: str
    base_url: str
    model: str
    enabled: bool
    default: bool = False


class ProviderRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def list_providers(self, *, selected: str | None = None) -> list[dict[str, object]]:
        selected_name = selected or self.settings.active_chat_provider
        # Missing providers are still listed so the harness can teach the full
        # ecosystem without requiring every API key during local development.
        providers = [
            ProviderDefinition(
                name="deepseek",
                display_name="DeepSeek",
                base_url=self.settings.deepseek_base_url,
                model=self.settings.deepseek_model,
                enabled=bool(self.settings.deepseek_api_key),
                default=selected_name == "deepseek",
            ),
            ProviderDefinition(
                "openai",
                "OpenAI",
                self.settings.openai_base_url,
                self.settings.openai_model,
                bool(self.settings.openai_api_key),
                selected_name == "openai",
            ),
            ProviderDefinition("anthropic", "Anthropic", "", "", False),
            ProviderDefinition("gemini", "Gemini", "", "", False),
            ProviderDefinition(
                "qwen",
                "Qwen",
                self.settings.qwen_embedding_base_url,
                self.settings.qwen_chat_model,
                bool(self.settings.qwen_api_key),
                selected_name == "qwen",
            ),
            ProviderDefinition(
                "openrouter",
                "OpenRouter",
                self.settings.openrouter_base_url,
                self.settings.openrouter_model,
                bool(self.settings.openrouter_api_key and self.settings.openrouter_model),
                selected_name == "openrouter",
            ),
            ProviderDefinition("ollama", "Ollama", "http://localhost:11434", "", False),
        ]
        return [
            {
                "name": provider.name,
                "display_name": provider.display_name,
                "base_url": provider.base_url,
                "model": provider.model,
                "enabled": provider.enabled,
                "default": provider.default,
                "key_status": "configured" if provider.enabled else "missing",
            }
            for provider in providers
        ]

    def get_chat_provider(self, *, selected: str | None = None) -> ChatProvider | None:
        name = selected or self.settings.active_chat_provider
        # Returning None is intentional: AgentKernel will use the deterministic
        # graph path, which keeps tests and first-run demos stable without keys.
        if name == "deepseek" and self.settings.deepseek_api_key:
            return DeepSeekClient(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
                model=self.settings.deepseek_model,
            )
        if name == "openai" and self.settings.openai_api_key:
            return OpenAICompatibleChatProvider(
                name="openai",
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
                model=self.settings.openai_model,
            )
        if (
            name == "openrouter"
            and self.settings.openrouter_api_key
            and self.settings.openrouter_model
        ):
            return OpenAICompatibleChatProvider(
                name="openrouter",
                api_key=self.settings.openrouter_api_key,
                base_url=self.settings.openrouter_base_url,
                model=self.settings.openrouter_model,
            )
        if name == "qwen" and self.settings.qwen_api_key:
            return OpenAICompatibleChatProvider(
                name="qwen",
                api_key=self.settings.qwen_api_key,
                base_url=self.settings.qwen_embedding_base_url,
                model=self.settings.qwen_chat_model,
            )
        return None
