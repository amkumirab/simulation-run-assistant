# Telegram bot setup

Simulation Run Assistant can send job notifications and run an authorized
long-polling command bot. It uses the Python standard library and does not need a
public server, domain, or webhook.

## Security first

- Never commit or paste a real bot token into source code, issues, logs, or chat.
- If a token is exposed, revoke it immediately with BotFather and generate a new
  one.
- Restrict commands with `TELEGRAM_CHAT_ID`. Messages from every other chat are
  ignored.
- Keep the dashboard bound to localhost unless a separate security layer is in
  place.

## 1. Create the bot

Create a bot with [BotFather](https://t.me/BotFather) and keep the generated
token private. The token is only read from the process environment.

Recommended BotFather metadata:

```text
Name: Simulation Run Assistant
Username: simulation_run_assistant_bot
Description: Monitor and control local simulation queues from Telegram.
About: Queue status, simulation results, retries, and run notifications.
```

The command list, description, and short profile description are configured
automatically when `sim-assistant bot` starts. A profile picture must still be
set manually in BotFather if desired.

## 2. Configure the token temporarily

Windows PowerShell:

```powershell
$env:TELEGRAM_BOT_TOKEN="PASTE_THE_NEW_TOKEN_HERE"
```

macOS or Linux:

```bash
export TELEGRAM_BOT_TOKEN="PASTE_THE_NEW_TOKEN_HERE"
```

Do not put the real value in `.env.example`. This project does not automatically
load `.env` files.

Verify that the token belongs to the expected bot before continuing. In Windows
PowerShell, the following command references the environment variable without
placing the token itself in command history:

```powershell
Invoke-RestMethod "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/getMe"
```

Check that the returned `username` is the bot you created. If Telegram returns
an authorization error, revoke the token in BotFather, generate a new one, and
replace the environment variable.

## 3. Discover the authorized chat ID

Open the bot in Telegram after configuring the current token. Press **Start**
and also type and send `/start` manually. A message sent before the latest token
was generated may not be available to the current session. Then run:

```bash
sim-assistant telegram-id
```

The command prints recent chat IDs without requiring a third-party bot. Copy the
ID for your private chat.

At this stage the bot does not reply to `/start`. The `telegram-id` command only
reads recent updates so the authorized chat can be discovered. Interactive
replies begin after `sim-assistant bot` is running.

## 4. Configure the authorized chat

Windows PowerShell:

```powershell
$env:TELEGRAM_CHAT_ID="YOUR_NUMERIC_CHAT_ID"
```

macOS or Linux:

```bash
export TELEGRAM_CHAT_ID="YOUR_NUMERIC_CHAT_ID"
```

## 5. Test notifications

Queue a demo and run it:

```bash
sim-assistant enqueue examples/em_sweep.json
sim-assistant run --limit 1
```

The authorized chat receives a success or failure notification.

## 6. Run the command bot

```bash
sim-assistant bot
```

Keep this process running. Stop it with `Ctrl+C`. Available commands:

```text
/status          Show queue totals
/jobs [limit]    List 1 to 10 recent jobs
/job ID          Show status, metrics, and error for one job
/run [limit]     Process 1 to 10 queued jobs; default is 1
/retry ID        Return a failed or cancelled job to the queue
/cancel ID       Cancel one queued job
/pause           Pause new queue claims
/resume          Resume queue processing
/help            Show command help
```

The default `/run` limit is intentionally one so an accidental command cannot
start an unlimited batch.

Wait for a startup message similar to this before testing commands in Telegram:

```text
Telegram bot @your_bot_username is running for chat 123456789.
```

Now send `/start` again. The bot should reply with its command list. GitHub only
stores the source code; it does not keep this foreground process online. Use an
always-on machine or a hosting service if the bot must respond continuously.

## Persistent Windows configuration

For a personal development machine, store the values in your user environment:

```powershell
[Environment]::SetEnvironmentVariable(
  "TELEGRAM_BOT_TOKEN",
  "PASTE_THE_NEW_TOKEN_HERE",
  "User"
)
[Environment]::SetEnvironmentVariable(
  "TELEGRAM_CHAT_ID",
  "YOUR_NUMERIC_CHAT_ID",
  "User"
)
```

Close and reopen PowerShell after setting persistent variables. Be aware that
other processes running as your Windows user may be able to read user-level
environment variables. A dedicated secret manager is preferable for production.

## Troubleshooting

### No chats are found

1. Run the `getMe` verification command and check the returned username.
2. Open that exact bot in Telegram.
3. Type and send `/start` manually after setting the latest token.
4. Immediately run `sim-assistant telegram-id` again.

Do not expect a Telegram reply during discovery; the responder is not running
yet.

### `getUpdates` reports a webhook conflict

Long polling and webhooks cannot be active at the same time. Remove the existing
webhook before running this bot, or deploy a separate webhook-based integration.

Inspect the current webhook configuration from PowerShell:

```powershell
Invoke-RestMethod "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

For a bot that should use this project's long-polling mode, remove an existing
webhook with:

```powershell
Invoke-RestMethod -Method Post "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/deleteWebhook"
```

### The bot stops when the terminal closes

The bot is a foreground process. Use a process manager, Windows Task Scheduler,
or a service wrapper if it must run continuously.

### Notifications work but commands do not

Confirm that `TELEGRAM_CHAT_ID` matches the numeric ID printed by
`sim-assistant telegram-id`, then restart `sim-assistant bot`.
