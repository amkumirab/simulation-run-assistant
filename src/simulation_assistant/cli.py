from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from simulation_assistant.manifest import load_manifest
from simulation_assistant.notifications import notifier_from_environment
from simulation_assistant.runner import SimulationRunner
from simulation_assistant.storage import JobStore
from simulation_assistant.telegram_api import TelegramBotApi
from simulation_assistant.telegram_bot import discover_chat_ids, run_bot
from simulation_assistant.types import JobStatus
from simulation_assistant.web import serve_dashboard
from simulation_assistant.adapters.comsol import ComsolConfig, check_comsol


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sim-assistant",
        description="Queue, run, and inspect reproducible simulation sweeps.",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("SIM_ASSISTANT_DB", ".sim-assistant/jobs.db"),
        help="SQLite database path (default: .sim-assistant/jobs.db)",
    )
    parser.add_argument(
        "--artifacts",
        default=os.getenv("SIM_ASSISTANT_ARTIFACTS", "artifacts"),
        help="Result artifact directory (default: artifacts)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the local job database")

    enqueue = subparsers.add_parser("enqueue", help="Add a JSON batch manifest")
    enqueue.add_argument("manifest", help="Path to a batch manifest")

    run = subparsers.add_parser("run", help="Run queued jobs in the foreground")
    run.add_argument("--limit", type=int, help="Maximum number of jobs to process")

    list_jobs = subparsers.add_parser("list", help="List recent jobs")
    list_jobs.add_argument("--status", choices=[status.value for status in JobStatus])
    list_jobs.add_argument("--limit", type=int, default=50)

    show = subparsers.add_parser("show", help="Show one job as JSON")
    show.add_argument("job_id", type=int)

    retry = subparsers.add_parser(
        "retry", help="Requeue one failed or cancelled job"
    )
    retry.add_argument("job_id", type=int)

    cancel = subparsers.add_parser("cancel", help="Cancel one queued job")
    cancel.add_argument("job_id", type=int)

    subparsers.add_parser("pause", help="Pause the persistent run queue")
    subparsers.add_parser("resume", help="Resume the persistent run queue")

    recover = subparsers.add_parser(
        "recover",
        help="Resolve jobs left running by an interrupted worker",
    )
    recover.add_argument(
        "--fail",
        action="store_true",
        help="Mark interrupted jobs failed instead of returning them to the queue",
    )

    serve = subparsers.add_parser("serve", help="Start the local assistant dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)

    subparsers.add_parser(
        "desktop",
        help="Start the native desktop assistant (no web server required)",
    )

    subparsers.add_parser(
        "telegram-id",
        help="Discover chat IDs from recent Telegram messages",
    )
    subparsers.add_parser(
        "bot",
        help="Run the authorized Telegram command bot",
    )

    comsol_check = subparsers.add_parser(
        "comsol-check",
        help="Validate COMSOL and inspect an MPH model's license requirements",
    )
    comsol_check.add_argument("--model", help="Path to the MPH model")
    comsol_check.add_argument("--executable", help="Path to comsolbatch.exe")
    comsol_check.add_argument("--study", help="Study tag to run")
    comsol_check.add_argument("--job", help="COMSOL job-sequence tag to run")
    comsol_check.add_argument("--timeout", type=int, help="Run timeout in seconds")
    comsol_check.add_argument("--cores", type=int, help="Number of COMSOL cores")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = JobStore(args.database)
    store.initialize()

    try:
        if args.command == "init":
            print(f"Initialized database: {Path(args.database).resolve()}")
        elif args.command == "enqueue":
            manifest = load_manifest(args.manifest)
            job_ids = store.enqueue_batch(manifest.name, manifest.adapter, manifest.jobs)
            print(
                f"Enqueued {len(job_ids)} job(s) in batch '{manifest.name}' "
                f"(IDs {job_ids[0]}..{job_ids[-1]})."
            )
        elif args.command == "run":
            summary = SimulationRunner(
                store=store,
                artifact_root=args.artifacts,
                notifier=notifier_from_environment(),
            ).run_pending(limit=args.limit)
            print(
                f"Processed {summary.processed}: "
                f"{summary.succeeded} succeeded, {summary.failed} failed."
            )
        elif args.command == "list":
            status = JobStatus(args.status) if args.status else None
            _print_jobs(store.list(status=status, limit=args.limit))
        elif args.command == "show":
            print(json.dumps(store.get(args.job_id).to_dict(), indent=2))
        elif args.command == "retry":
            store.retry(args.job_id)
            print(f"Job {args.job_id} was returned to the queue.")
        elif args.command == "cancel":
            store.cancel(args.job_id)
            print(f"Job {args.job_id} was cancelled.")
        elif args.command == "pause":
            store.set_queue_paused(True)
            print("Run queue paused. The active job is not interrupted.")
        elif args.command == "resume":
            store.set_queue_paused(False)
            print("Run queue resumed.")
        elif args.command == "recover":
            recovered = store.recover_interrupted(requeue=not args.fail)
            action = "marked failed" if args.fail else "returned to the queue"
            print(f"Recovered {len(recovered)} interrupted job(s): {action}.")
        elif args.command == "serve":
            serve_dashboard(args.database, args.artifacts, args.host, args.port)
        elif args.command == "desktop":
            from simulation_assistant.desktop import run_desktop

            run_desktop(args.database, args.artifacts)
        elif args.command == "telegram-id":
            token = _required_environment("TELEGRAM_BOT_TOKEN")
            chats = discover_chat_ids(TelegramBotApi(token))
            if not chats:
                print("No recent chats found. Send /start to the bot and try again.")
            else:
                print("CHAT ID              TYPE         TITLE")
                print("-" * 64)
                for chat in chats:
                    print(f"{chat['id']:<20} {chat['type']:<12} {chat['title']}")
        elif args.command == "bot":
            token = _required_environment("TELEGRAM_BOT_TOKEN")
            chat_id = _required_environment("TELEGRAM_CHAT_ID")
            run_bot(
                api=TelegramBotApi(token),
                store=store,
                artifact_root=args.artifacts,
                allowed_chat_id=chat_id,
            )
        elif args.command == "comsol-check":
            config = ComsolConfig.from_environment(
                executable=args.executable,
                model_path=args.model,
                study_tag=args.study,
                job_tag=args.job,
                timeout_seconds=args.timeout,
                cores=args.cores,
            )
            print(json.dumps(check_comsol(config), indent=2))
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Environment variable {name} is required")
    return value


def _print_jobs(jobs: list) -> None:
    if not jobs:
        print("No jobs found.")
        return
    print(f"{'ID':>5}  {'STATUS':<10}  {'ADAPTER':<12}  {'ATTEMPTS':>8}  BATCH")
    print("-" * 72)
    for job in jobs:
        print(
            f"{job.id:>5}  {job.status.value:<10}  {job.adapter:<12}  "
            f"{job.attempts:>8}  {job.batch_name}"
        )


if __name__ == "__main__":
    main()
