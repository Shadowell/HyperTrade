"""Runtime provider router.

ProviderRuntime is the single place that turns environment configuration into a
chat provider. It never exposes API keys in status payloads; API, CLI, and the
frontend only see provider names, model names, and key status.
"""

from dataclasses import dataclass

from hypertrade.config import Settings
from hypertrade.providers.chat import ChatProvider, OpenAICompatibleChatProvider
from hypertrade.providers.codex import CodexResponsesChatProvider, resolve_codex_access_token
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
    PROVIDER_ALIASES = {"openai-codex": "codex", "openai_codex": "codex"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    def normalize_provider_name(cls, name: str | None) -> str:
        cleaned = (name or "").strip().lower()
        return cls.PROVIDER_ALIASES.get(cleaned, cleaned)

    def list_providers(self, *, selected: str | None = None) -> list[dict[str, object]]:
        selected_name = self.normalize_provider_name(selected or self.settings.active_chat_provider)
        codex_token = resolve_codex_access_token(
            api_key=self.settings.codex_api_key,
            auth_json=self.settings.codex_auth_json,
        )
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
            ProviderDefinition(
                "codex",
                "Codex",
                self.settings.codex_base_url,
                self.settings.codex_model,
                bool(codex_token),
                selected_name == "codex",
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
        name = self.normalize_provider_name(selected or self.settings.active_chat_provider)
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
        if name == "codex":
            codex_token = resolve_codex_access_token(
                api_key=self.settings.codex_api_key,
                auth_json=self.settings.codex_auth_json,
            )
            if codex_token:
                return CodexResponsesChatProvider(
                    api_key=codex_token,
                    base_url=self.settings.codex_base_url,
                    model=self.settings.codex_model,
                    timeout_seconds=self.settings.codex_timeout_seconds,
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
