# Telegram bot security architecture

## Threat model and facts confirmed from this repository

The application creates one aiogram `Bot`, runs `Dispatcher.start_polling`, keeps its configuration in Pydantic settings (`.env` by default) plus YAML, uses APScheduler in the same process, and stores business data in async SQLite. The former health check constructed a token-bearing Bot API URL and printed exception text; `urllib` errors can include that full URL. Deployment also kept `.env` inside the working tree and migration backups copied it. Those are **confirmed risks**. `.gitignore` excluded `.env`, and the process did not intentionally call `setWebhook` or `setMyName`.

The **likely** incident cause is off-host token use, but its source cannot be proved from local logs. Potential sources include readable deployment copies, operator workstations, shell/editor history, CI variables, old `/opt/cocbot-prev-*` trees, migration staging, and backups. Preserve evidence before cleaning any of them.

Telegram polling (`getUpdates`) and webhook delivery are mutually exclusive. A token holder can call Bot API methods as the bot, change mutable profile data, install a webhook, send bot messages, and receive updates made available to that bot. A bot token does not grant a Telegram user account, server root access, or historical messages Telegram never exposes to that bot.

Telegram Bot API does not provide caller-IP/API-call audit history or the exact updates delivered successfully to a hostile webhook. Pending count is only the queue at observation time. Update-ID gaps are indicators, not proof or an exact stolen-message count.

## Implemented contour

Before startup synchronization and polling, the monitor verifies immutable ID/username, reads webhook state, records a sanitized evidence event, deletes any webhook with `drop_pending_updates=False`, and confirms it is empty. Failure aborts startup. An in-process task repeats every 30–300 seconds (45 by default); it never calls `getUpdates` and creates no second polling process. It remains independent of SQLite, though a completely wedged process requires external service monitoring.

The baseline supports ID, username, display name, description, short description, and commands. Webhook repair is unconditional in polling mode; profile repair is opt-in. Evidence is written before repair. Repeated detections in ten minutes become CRITICAL; alerts are deduplicated for ten minutes.

Security and update metadata are JSONL files at mode `0600`, with rotation and a hash chain. The chain detects some accidental/incomplete edits but is not tamper-proof against root or an attacker able to rewrite the log and chain. Update audit stores IDs, timestamps, type, chat/user IDs, duration, result and error class—never message/caption/callback contents. Default file rotation is size-based; operators should additionally retain no more than 30 days with logrotate.

Alerts always reach journald/security audit. Admin chats via the primary bot are fallback. Set `SENTINEL_BOT_TOKEN` and comma-separated `SENTINEL_ADMIN_CHAT_IDS` for an independent bot; its token must differ. Absence does not prevent startup and is visible as an unavailable alert result.

## Production checklist

1. Rotate the compromised token via BotFather immediately.
2. Set all `telegram_security.expected_*` baseline fields, especially ID and username.
3. Migrate the environment file to `/etc/cocbot/cocbot.env`, owner `root:cocbot`, mode `0640`; do not delete the old copy until evidence preservation and rotation are complete.
4. Configure the sentinel, filesystem monitoring and off-host collection of security logs.
5. Review `/opt/cocbot-prev-*`, backups, archives, systemd overrides, CI secrets, operator shell history, cron/timers, processes and connections without printing secret contents.
6. Run `scripts/scan_secrets.py --history`; rotate first if it reports a fingerprint. History rewrite is a separately coordinated operation and deleting a current file does not remove old commits.

Registration still accepts a player token in a Telegram message. Options requiring product approval are: retain this flow; delete the message after verification (reduces later exposure only); use a one-time external HTTPS verification flow; or use a purpose-built short-lived challenge. Deletion cannot protect an update already delivered to a hostile webhook.
