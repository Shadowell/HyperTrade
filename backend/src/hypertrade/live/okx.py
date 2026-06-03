from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from hypertrade.config import Settings


class OkxSignedRestClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def place_order(
        self,
        *,
        inst_id: str,
        side: str,
        order_type: str,
        size: str,
        price: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "instId": inst_id,
            "tdMode": "cross",
            "side": side,
            "ordType": order_type,
            "sz": size,
        }
        if order_type == "limit" and price:
            body["px"] = price
        path = "/api/v5/trade/order"
        body_text = json.dumps(body, separators=(",", ":"))
        timestamp = _timestamp()
        headers = {
            "OK-ACCESS-KEY": self.settings.okx_api_key,
            "OK-ACCESS-SIGN": _sign(
                secret=self.settings.okx_api_secret,
                timestamp=timestamp,
                method="POST",
                path=path,
                body=body_text,
            ),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.settings.okx_passphrase,
            "Content-Type": "application/json",
        }
        if self.settings.okx_testnet:
            headers["x-simulated-trading"] = "1"
        with httpx.Client(base_url=self.settings.okx_rest_url, timeout=15) as client:
            response = client.post(path, content=body_text, headers=headers)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("OKX order response must be a JSON object")
        return payload


def redacted_order_request(
    *,
    settings: Settings,
    inst_id: str,
    side: str,
    order_type: str,
    size: str,
    price: str | None,
) -> dict[str, Any]:
    return {
        "api_key": "***" if settings.okx_api_key else "",
        "secret": "***" if settings.okx_api_secret else "",
        "passphrase": "***" if settings.okx_passphrase else "",
        "testnet": settings.okx_testnet,
        "inst_id": inst_id,
        "side": side,
        "order_type": order_type,
        "size": size,
        "price": price,
    }


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sign(*, secret: str, timestamp: str, method: str, path: str, body: str) -> str:
    message = f"{timestamp}{method.upper()}{path}{body}"
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()
