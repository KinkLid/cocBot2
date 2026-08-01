# Safe Telegram token rotation

Bot API cannot mint a replacement. The owner must revoke/reissue the token manually through BotFather.

## Secret-file preparation

Create `/etc/cocbot/cocbot.env` as root, owner `root:cocbot`, mode `0640`. The systemd unit reads the project `.env` first and the external file second, so external values override during migration. Deployment and migration scripts do not create persistent `.env` backup copies. Existing historical copies still require evidence-aware cleanup after rotation.

## Rotation command

Configure `expected_bot_id` and `expected_username` first, then run:

```console
sudo /opt/cocbot/.venv/bin/python \
  /opt/cocbot/scripts/rotate_telegram_token.py \
  --project-dir /opt/cocbot \
  --secret-file /etc/cocbot/cocbot.env
```

The token is accepted only through a hidden prompt. The script:

1. validates the new token identity;
2. deletes its webhook with `drop_pending_updates=False` and verifies it is empty;
3. atomically replaces the secret file without a plaintext backup;
4. restarts only `cocbot`;
5. waits for a security heartbeat whose token fingerprint and bot ID match the new token;
6. checks the webhook again;
7. records explicit validation, replacement, post-check, and completion events.

If validation fails, the secret is unchanged. If a failure happens after replacement, the error explicitly says that the secret file has already changed. Do not restore the compromised token. Inspect `systemctl status cocbot`, `journalctl -u cocbot`, configuration, file ownership, and the security state, then complete recovery with another BotFather-issued token if required.
