# Telegram bot security architecture

## Threat model and confirmed repository facts

The application runs one aiogram `Dispatcher.start_polling` process, loads secrets from environment files, uses APScheduler in the same process, and stores business data in async SQLite. Telegram polling and webhook delivery are mutually exclusive: a successful external `setWebhook` terminates polling.

A holder of the bot token can call Bot API methods as the bot, install a webhook, receive updates made available to the bot, send bot messages, and change mutable profile fields. A bot token does not grant the owner's Telegram user account, server root access, or historical messages Telegram does not expose to bots.

Telegram Bot API does not expose caller IPs, API-call history, or the exact updates successfully delivered to another webhook. Pending count is only the queue at observation time. Update-ID gaps are indicators, not proof or an exact stolen-message count.

## Implemented security contour

Before startup synchronization, the monitor calls `getMe`, checks the configured identity baseline when present, inspects webhook state, records sanitized evidence, removes any webhook with `drop_pending_updates=False`, and verifies that it is empty. Monitoring remains active during startup synchronization and polling. A fatal failure to remove a webhook terminates the process so systemd cannot report a healthy but nonresponsive bot.

For backwards compatibility, an existing configuration without `expected_bot_id` continues to start and still receives webhook monitoring, but emits `security_baseline_incomplete`. Set `require_identity_baseline: true` only after `expected_bot_id` and `expected_username` are populated. New production deployments should enable strict identity checking.

The baseline can monitor bot ID, username, display name, description, short description, and commands. Webhook repair is unconditional in polling mode. Profile repair is opt-in. Evidence is written before any repair. A repeated webhook within ten minutes escalates to CRITICAL and bypasses lower-severity alert deduplication. Alert cooldown state is persisted across process restarts.

Security audit, update audit, and incident state are independent of SQLite. JSONL writes use a file lock, mode `0600`, rotation, and a hash chain that continues across multiple writers, process restarts, and rotated files. The chain can reveal accidental or incomplete modification, but it is not tamper-proof against root or an attacker able to rewrite all evidence.

Each webhook occurrence receives a separate incident ID and stores:

- last confirmed empty-webhook check before that incident;
- detection and removal/failure timestamps;
- sanitized host, port, scheme, and URL fingerprint;
- pending update count;
- first update received after recovery.

Update audit stores update ID, timestamps, update type, chat/user IDs, handler name, handled/not-handled result, duration, and safe error class. It never serializes message text, captions, callback payloads, media, player tags, or player tokens. Maximum received/completed update IDs are monotonic even when handlers finish out of order.

## Alerts

Journald and the security audit are always used. Primary-bot admin messages are a fallback and may be unavailable during an incident. For an independent channel configure a separate bot through `SENTINEL_BOT_TOKEN` and `SENTINEL_ADMIN_CHAT_IDS`. The sentinel token must differ from the primary token.

## Production checklist

1. Revoke and reissue the compromised token through BotFather.
2. Set `expected_bot_id`, `expected_username`, expected profile fields, then set `require_identity_baseline: true`.
3. Store the active environment file at `/etc/cocbot/cocbot.env`, owner `root:cocbot`, mode `0640`.
4. Configure a sentinel bot and off-host collection of security logs.
5. Review old deployments, archives, CI secrets, operator workstations, shell/editor history, cron/timers, processes, and network connections without printing secret contents.
6. Run `scripts/scan_secrets.py --history`; rotate first if it reports a fingerprint. Rewriting Git history is a separate coordinated operation.
7. Retain security evidence off-host. Local size rotation is not a substitute for centralized retention.

Registration still receives a Clash player token in a Telegram message. Deleting that message after verification reduces later exposure but cannot protect an update already delivered to a hostile webhook. A one-time external HTTPS verification flow requires a separate product/design decision.
