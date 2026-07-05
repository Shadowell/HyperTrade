#!/usr/bin/env python3
"""Test Vide Coding API provider integration.

This script verifies that the Vide Coding provider is correctly configured
and can communicate with the API.
"""

import os
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent / "backend" / "src"
sys.path.insert(0, str(backend_path))

from hypertrade.config import get_settings
from hypertrade.providers.runtime import ProviderRuntime


def test_vide_coding_config():
    """Test Vide Coding configuration."""
    print("🔧 Testing Vide Coding Configuration...")

    settings = get_settings()

    # Check configuration
    print(f"✓ Base URL: {settings.vide_coding_base_url}")
    print(f"✓ Model: {settings.vide_coding_model}")
    print(f"✓ API Key configured: {'Yes' if settings.vide_coding_api_key else 'No'}")
    print(f"✓ Active Provider: {settings.active_chat_provider}")

    if not settings.vide_coding_api_key:
        print("❌ VIDE_CODING_API_KEY not set in .env")
        return False

    if settings.active_chat_provider != "vide_coding":
        print("⚠️  Active provider is not vide_coding")

    return True


def test_provider_runtime():
    """Test ProviderRuntime with Vide Coding."""
    print("\n🚀 Testing Provider Runtime...")

    settings = get_settings()
    runtime = ProviderRuntime(settings)

    # List providers
    providers = runtime.list_providers(selected="vide_coding")
    vide_provider = next(
        (p for p in providers if p.get("name") == "vide_coding"),
        None
    )

    if not vide_provider:
        print("❌ Vide Coding provider not found in provider list")
        return False

    print(f"✓ Provider found: {vide_provider.get('display_name')}")
    print(f"✓ Configured: {vide_provider.get('configured')}")
    print(f"✓ Selected: {vide_provider.get('selected')}")
    print(f"✓ Model: {vide_provider.get('model')}")

    # Get chat model
    try:
        chat_model = runtime.get_chat_provider(selected="vide_coding")
        if chat_model:
            print(f"✓ Chat model instance created: {type(chat_model).__name__}")
            print(f"✓ Provider name: {chat_model.name}")
            print(f"✓ Model: {chat_model.model}")
            return True
        else:
            print("❌ Failed to create chat model instance")
            return False
    except Exception as e:
        print(f"❌ Error creating chat model: {e}")
        return False


def test_api_connection():
    """Test API connection (optional - requires valid key)."""
    print("\n🌐 Testing API Connection...")

    settings = get_settings()

    if not settings.vide_coding_api_key:
        print("⚠️  Skipping API connection test (no API key)")
        return True

    try:
        runtime = ProviderRuntime(settings)
        chat_model = runtime.get_chat_provider(selected="vide_coding")

        if not chat_model:
            print("❌ Failed to get chat model")
            return False

        # Try a simple completion
        print("Sending test message to Vide Coding API...")
        messages = [{"role": "user", "content": "Say 'Hello from HyperTrade!'"}]

        response = chat_model.chat(messages=messages)

        if response and "choices" in response:
            content = response["choices"][0]["message"]["content"]
            print(f"✓ API Response: {content[:100]}...")
            return True
        else:
            print("❌ Unexpected API response format")
            return False

    except Exception as e:
        print(f"❌ API connection failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Vide Coding Provider Integration Test")
    print("=" * 60)

    results = []

    # Test configuration
    results.append(("Configuration", test_vide_coding_config()))

    # Test provider runtime
    results.append(("Provider Runtime", test_provider_runtime()))

    # Test API connection (optional)
    results.append(("API Connection", test_api_connection()))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{name}: {status}")

    all_passed = all(result for _, result in results)

    if all_passed:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
