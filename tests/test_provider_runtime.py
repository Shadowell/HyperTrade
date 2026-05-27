from hypertrade.config import Settings
from hypertrade.providers.runtime import ProviderRuntime


def test_provider_status_hides_keys_and_uses_deepseek_default(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    runtime = ProviderRuntime(Settings())

    providers = runtime.list_providers()
    deepseek = next(provider for provider in providers if provider["name"] == "deepseek")

    assert deepseek["enabled"] is True
    assert deepseek["default"] is True
    assert deepseek["model"] == "deepseek-v4-flash"
    assert "sk-secret" not in str(deepseek)
