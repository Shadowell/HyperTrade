from dataclasses import dataclass

from hypertrade.config import Settings


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

    def list_providers(self) -> list[dict[str, object]]:
        providers = [
            ProviderDefinition(
                name="deepseek",
                display_name="DeepSeek",
                base_url=self.settings.deepseek_base_url,
                model=self.settings.deepseek_model,
                enabled=bool(self.settings.deepseek_api_key),
                default=True,
            ),
            ProviderDefinition("openai", "OpenAI", "", "", False),
            ProviderDefinition("anthropic", "Anthropic", "", "", False),
            ProviderDefinition("gemini", "Gemini", "", "", False),
            ProviderDefinition(
                "qwen",
                "Qwen",
                self.settings.qwen_embedding_base_url,
                self.settings.qwen_embedding_model,
                bool(self.settings.qwen_api_key),
            ),
            ProviderDefinition("openrouter", "OpenRouter", "", "", False),
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
