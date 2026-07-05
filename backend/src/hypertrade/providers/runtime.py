"""Runtime provider router.

ProviderRuntime is the single place that turns environment configuration into a
chat provider. It never exposes API keys in status payloads; API, CLI, and the
frontend only see provider names, model names, and key status.
"""

from collections.abc import Mapping
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
    model_options: tuple[str, ...] = ()


class ProviderRuntime:
    PROVIDER_ALIASES = {"openai-codex": "codex", "openai_codex": "codex"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    def normalize_provider_name(cls, name: str | None) -> str:
        cleaned = (name or "").strip().lower()
        return cls.PROVIDER_ALIASES.get(cleaned, cleaned)

    def list_providers(
        self,
        *,
        selected: str | None = None,
        selected_models: Mapping[str, str] | None = None,
    ) -> list[dict[str, object]]:
        selected_name = self.normalize_provider_name(selected or self.settings.active_chat_provider)
        selected_model_map = {
            self.normalize_provider_name(provider): model.strip()
            for provider, model in (selected_models or {}).items()
            if model.strip()
        }
        codex_model_options = self._codex_model_options()
        codex_model = selected_model_map.get("codex") or self.settings.codex_model
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
                codex_model,
                bool(codex_token),
                selected_name == "codex",
                codex_model_options,
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
            ProviderDefinition(
                "vide_coding",
                "Vide Coding",
                self.settings.vide_coding_base_url,
                self.settings.vide_coding_model,
                bool(self.settings.vide_coding_api_key),
                selected_name == "vide_coding",
            ),
            ProviderDefinition("ollama", "Ollama", "http://localhost:11434", "", False),
        ]
        return [
            {
                "name": provider.name,
                "display_name": provider.display_name,
                "base_url": provider.base_url,
                "model": provider.model,
                "model_options": list(
                    provider.model_options or ((provider.model,) if provider.model else ())
                ),
                "enabled": provider.enabled,
                "default": provider.default,
                "key_status": "configured" if provider.enabled else "missing",
            }
            for provider in providers
        ]

    def get_chat_provider(
        self,
        *,
        selected: str | None = None,
        selected_model: str | None = None,
    ) -> ChatProvider | None:
        name = self.normalize_provider_name(selected or self.settings.active_chat_provider)
        model_override = (selected_model or "").strip()
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
                    model=model_override or self.settings.codex_model,
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
        if name == "vide_coding" and self.settings.vide_coding_api_key:
            return OpenAICompatibleChatProvider(
                name="vide_coding",
                api_key=self.settings.vide_coding_api_key,
                base_url=self.settings.vide_coding_base_url,
                model=model_override or self.settings.vide_coding_model,
            )
        return None

    def validate_model_choice(self, provider: str, model: str | None) -> str:
        requested = (model or "").strip()
        if not requested:
            return ""
        normalized_provider = self.normalize_provider_name(provider)
        providers = self.list_providers(selected=normalized_provider)
        selected = next(
            (item for item in providers if item.get("name") == normalized_provider),
            None,
        )
        if selected is None:
            raise ValueError(f"unknown provider: {provider}")
        raw_options = selected.get("model_options", [])
        options = (
            [str(option) for option in raw_options if str(option)]
            if isinstance(raw_options, list | tuple)
            else []
        )
        if options and requested not in options:
            raise ValueError(f"unknown model for {normalized_provider}: {requested}")
        if not options and requested != str(selected.get("model", "")):
            raise ValueError(f"unknown model for {normalized_provider}: {requested}")
        return requested

    def _codex_model_options(self) -> tuple[str, ...]:
        configured = [
            item.strip()
            for item in self.settings.codex_model_options.split(",")
            if item.strip()
        ]
        current = self.settings.codex_model.strip()
        ordered = [current, *configured] if current else configured
        return tuple(dict.fromkeys(ordered))
