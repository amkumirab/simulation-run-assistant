from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


@dataclass(frozen=True)
class TelegramBotApi:
    """Minimal standard-library client for the Telegram Bot API."""

    token: str
    timeout_seconds: float = 35

    def get_me(self) -> dict[str, Any]:
        return self._call("getMe")

    def send_message(self, chat_id: str, text: str) -> None:
        self._call("sendMessage", {"chat_id": chat_id, "text": text[:4000]})

    def get_updates(
        self,
        offset: int | None = None,
        timeout_seconds: int = 25,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout_seconds,
            "allowed_updates": json.dumps(["message"]),
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call(
            "getUpdates",
            payload,
            timeout_seconds=max(self.timeout_seconds, timeout_seconds + 10),
        )
        if not isinstance(result, list):
            raise RuntimeError("Telegram returned an invalid updates response")
        return result

    def set_commands(self, commands: list[dict[str, str]]) -> None:
        self._call("setMyCommands", {"commands": json.dumps(commands)})

    def set_description(self, description: str) -> None:
        self._call("setMyDescription", {"description": description})

    def set_short_description(self, description: str) -> None:
        self._call(
            "setMyShortDescription",
            {"short_description": description},
        )

    def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        encoded = parse.urlencode(payload or {}).encode("utf-8")
        api_request = request.Request(url, data=encoded, method="POST")
        try:
            with request.urlopen(
                api_request,
                timeout=timeout_seconds or self.timeout_seconds,
            ) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raise RuntimeError(
                f"Telegram API request failed with HTTP {exc.code}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError("Telegram API request could not be completed") from exc

        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Telegram returned invalid JSON") from exc
        if not data.get("ok"):
            description = str(data.get("description", "request rejected"))
            raise RuntimeError(f"Telegram API error: {description}")
        return data.get("result")
