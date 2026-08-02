from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

from simulation_assistant.notifications import TelegramNotifier
from simulation_assistant.runner import SimulationRunner
from simulation_assistant.storage import JobStore


class TelegramApi(Protocol):
    token: str

    def get_me(self) -> dict[str, Any]: ...

    def send_message(self, chat_id: str, text: str) -> None: ...

    def get_updates(
        self,
        offset: int | None = None,
        timeout_seconds: int = 25,
    ) -> list[dict[str, Any]]: ...

    def set_commands(self, commands: list[dict[str, str]]) -> None: ...

    def set_description(self, description: str) -> None: ...

    def set_short_description(self, description: str) -> None: ...


COMMANDS = [
    {"command": "status", "description": "Show queue totals"},
    {"command": "jobs", "description": "List recent jobs"},
    {"command": "job", "description": "Show one job"},
    {"command": "run", "description": "Process queued jobs"},
    {"command": "retry", "description": "Retry a failed job"},
    {"command": "help", "description": "Show available commands"},
]

BOT_DESCRIPTION = (
    "Monitor a local Simulation Run Assistant queue, inspect job results, "
    "retry failures, and start bounded worker runs from an authorized chat."
)
BOT_SHORT_DESCRIPTION = "Monitor and control reproducible simulation runs."

HELP_TEXT = """Simulation Run Assistant

/status - show queue totals
/jobs [limit] - list 1 to 10 recent jobs
/job ID - show one job and its metrics
/run [limit] - process queued jobs (default limit: 1, maximum: 10)
/retry ID - return a failed job to the queue
/help - show this message

Only the configured Telegram chat can use this bot."""


class TelegramBotController:
    def __init__(
        self,
        api: TelegramApi,
        store: JobStore,
        artifact_root: str | Path,
        allowed_chat_id: str,
    ) -> None:
        self.api = api
        self.store = store
        self.artifact_root = Path(artifact_root)
        self.allowed_chat_id = str(allowed_chat_id)

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        text = message.get("text")
        if not isinstance(chat, dict) or not isinstance(text, str):
            return

        chat_id = str(chat.get("id", ""))
        if chat_id != self.allowed_chat_id:
            return

        command, arguments = _parse_command(text)
        try:
            response = self._execute(command, arguments)
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            response = f"Command failed: {exc}"
        self.api.send_message(chat_id, response)

    def _execute(self, command: str, arguments: list[str]) -> str:
        if command in {"/start", "/help"}:
            return HELP_TEXT
        if command == "/status":
            counts = self.store.counts()
            return (
                "Queue status\n"
                f"Queued: {counts['queued']}\n"
                f"Running: {counts['running']}\n"
                f"Succeeded: {counts['succeeded']}\n"
                f"Failed: {counts['failed']}"
            )
        if command == "/jobs":
            limit = _optional_limit(arguments, default=5)
            jobs = self.store.list(limit=limit)
            if not jobs:
                return "No jobs found."
            lines = ["Recent jobs"]
            lines.extend(
                f"#{job.id} | {job.status.value} | {job.adapter} | {job.batch_name}"
                for job in jobs
            )
            return "\n".join(lines)
        if command == "/job":
            job_id = _required_job_id(arguments)
            job = self.store.get(job_id)
            lines = [
                f"Job #{job.id}",
                f"Status: {job.status.value}",
                f"Batch: {job.batch_name}",
                f"Adapter: {job.adapter}",
                f"Attempts: {job.attempts}",
            ]
            if job.result and isinstance(job.result.get("metrics"), dict):
                lines.append("Metrics:")
                lines.extend(
                    f"- {key}: {value}"
                    for key, value in job.result["metrics"].items()
                )
            if job.error:
                lines.append(f"Error: {job.error}")
            return "\n".join(lines)
        if command == "/run":
            limit = _optional_limit(arguments, default=1)
            summary = SimulationRunner(
                store=self.store,
                artifact_root=self.artifact_root,
                notifier=TelegramNotifier(
                    token=self.api.token,
                    chat_id=self.allowed_chat_id,
                ),
            ).run_pending(limit=limit)
            return (
                f"Processed {summary.processed}: "
                f"{summary.succeeded} succeeded, {summary.failed} failed."
            )
        if command == "/retry":
            job_id = _required_job_id(arguments)
            self.store.retry(job_id)
            return f"Job #{job_id} returned to the queue."
        return "Unknown command. Use /help to see available commands."


def run_bot(
    api: TelegramApi,
    store: JobStore,
    artifact_root: str | Path,
    allowed_chat_id: str,
) -> None:
    identity = api.get_me()
    username = identity.get("username", "unknown")
    api.set_commands(COMMANDS)
    api.set_description(BOT_DESCRIPTION)
    api.set_short_description(BOT_SHORT_DESCRIPTION)
    controller = TelegramBotController(api, store, artifact_root, allowed_chat_id)
    print(f"Telegram bot @{username} is running for chat {allowed_chat_id}.")
    print("Press Ctrl+C to stop.")

    offset: int | None = None
    try:
        while True:
            try:
                updates = api.get_updates(offset=offset, timeout_seconds=25)
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                    controller.handle_update(update)
            except RuntimeError as exc:
                print(f"Telegram polling warning: {exc}")
                time.sleep(5)
    except KeyboardInterrupt:
        print("Telegram bot stopped.")


def discover_chat_ids(api: TelegramApi) -> list[dict[str, str]]:
    chats: dict[str, dict[str, str]] = {}
    for update in api.get_updates(timeout_seconds=0):
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        if not isinstance(chat, dict) or "id" not in chat:
            continue
        chat_id = str(chat["id"])
        chats[chat_id] = {
            "id": chat_id,
            "type": str(chat.get("type", "unknown")),
            "title": str(
                chat.get("title")
                or chat.get("username")
                or chat.get("first_name")
                or "unknown"
            ),
        }
    return list(chats.values())


def _parse_command(text: str) -> tuple[str, list[str]]:
    parts = text.strip().split()
    if not parts:
        return "", []
    command = parts[0].split("@", 1)[0].lower()
    return command, parts[1:]


def _optional_limit(arguments: list[str], default: int) -> int:
    if len(arguments) > 1:
        raise ValueError("Provide at most one limit")
    if not arguments:
        return default
    try:
        limit = int(arguments[0])
    except ValueError as exc:
        raise ValueError("Limit must be an integer") from exc
    if not 1 <= limit <= 10:
        raise ValueError("Limit must be between 1 and 10")
    return limit


def _required_job_id(arguments: list[str]) -> int:
    if len(arguments) != 1:
        raise ValueError("Provide exactly one job ID")
    try:
        job_id = int(arguments[0])
    except ValueError as exc:
        raise ValueError("Job ID must be an integer") from exc
    if job_id < 1:
        raise ValueError("Job ID must be positive")
    return job_id
