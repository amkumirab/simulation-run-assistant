from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from simulation_assistant.telegram_api import TelegramBotApi


class Notifier(Protocol):
    def send(self, message: str) -> None: ...


class NullNotifier:
    def send(self, message: str) -> None:
        return None


@dataclass(frozen=True)
class TelegramNotifier:
    token: str
    chat_id: str
    timeout_seconds: float = 10

    def send(self, message: str) -> None:
        TelegramBotApi(self.token, self.timeout_seconds).send_message(
            self.chat_id,
            message,
        )


def notifier_from_environment() -> Notifier:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return TelegramNotifier(token=token, chat_id=chat_id)
    return NullNotifier()
