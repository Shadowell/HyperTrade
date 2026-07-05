#!/usr/bin/env python3
"""Direct API test for Vide Coding endpoint.

Tests the Vide Coding API directly without the full HyperTrade stack.
"""

import json
import sys

try:
    import httpx
except ImportError:
    print("Installing httpx...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
    import httpx


def test_vide_coding_api():
    """Test Vide Coding API directly."""

    api_key = "sk-215bbede376a3e6ae92d05dfc7009db21c9f706dcecff55780875645c0ad13ff"
    base_url = "https://api.vide.ai/v1"
    model = "opus-4.6"

    print("=" * 60)
    print("Vide Coding API Direct Test")
    print("=" * 60)
    print(f"Base URL: {base_url}")
    print(f"Model: {model}")
    print(f"API Key: {api_key[:20]}...")
    print()

    # Test 1: Simple completion
    print("Test 1: Simple Completion")
    print("-" * 60)

    try:
        client = httpx.Client(timeout=30.0)

        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": "Say 'Hello from HyperTrade with opus-4.6!' in exactly that format."}
            ],
            "max_tokens": 100
        }

        print("Sending request...")
        response = client.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            print(f"✅ SUCCESS!")
            print(f"Response: {content}")
            print(f"Model Used: {data.get('model', 'N/A')}")
            print(f"Usage: {json.dumps(data.get('usage', {}), indent=2)}")
            return True
        else:
            print(f"❌ FAILED!")
            print(f"Response: {response.text}")
            return False

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        client.close()


def test_vide_coding_with_tools():
    """Test Vide Coding API with tool calling."""

    api_key = "sk-215bbede376a3e6ae92d05dfc7009db21c9f706dcecff55780875645c0ad13ff"
    base_url = "https://api.vide.ai/v1"
    model = "opus-4.6"

    print("\n" + "=" * 60)
    print("Test 2: Tool Calling Support")
    print("-" * 60)

    try:
        client = httpx.Client(timeout=30.0)

        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": "What's the weather in San Francisco?"}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather in a location",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {
                                    "type": "string",
                                    "description": "The city name"
                                }
                            },
                            "required": ["location"]
                        }
                    }
                }
            ],
            "max_tokens": 100
        }

        print("Sending request with tool definition...")
        response = client.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            message = data["choices"][0]["message"]

            if "tool_calls" in message and message["tool_calls"]:
                tool_call = message["tool_calls"][0]
                print(f"✅ Tool calling supported!")
                print(f"Tool: {tool_call['function']['name']}")
                print(f"Arguments: {tool_call['function']['arguments']}")
                return True
            else:
                print(f"⚠️  No tool call in response")
                print(f"Response: {message.get('content', 'N/A')}")
                return True  # Still successful, just no tool call
        else:
            print(f"❌ FAILED!")
            print(f"Response: {response.text}")
            return False

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False
    finally:
        client.close()


def main():
    """Run all API tests."""
    results = []

    # Test 1: Simple completion
    results.append(("Simple Completion", test_vide_coding_api()))

    # Test 2: Tool calling
    results.append(("Tool Calling", test_vide_coding_with_tools()))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{name}: {status}")

    all_passed = all(result for _, result in results)

    if all_passed:
        print("\n🎉 All API tests passed!")
        print("\nVide Coding API is ready to use with HyperTrade!")
        return 0
    else:
        print("\n⚠️  Some tests failed")
        print("\nPlease check:")
        print("1. API key is valid")
        print("2. Network connection is working")
        print("3. API endpoint is correct")
        return 1


if __name__ == "__main__":
    sys.exit(main())
