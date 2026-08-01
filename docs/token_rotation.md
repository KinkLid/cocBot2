# Safe Telegram token rotation

Bot API cannot mint a replacement. The owner must revoke/reissue it manually through BotFather.

## Secret-file migration

After preserving incident evidence, create `/etc/cocbot/cocbot.env` as root without displaying it, copy the required environment assignments through an editor restricted to root, then run `chown root:cocbot /etc/cocbot/cocbot.env && chmod 0640 /etc/cocbot/cocbot.env`. The unit reads the legacy project `.env` first and the external file second, so external values override during migration. Deploy scripts never overwrite the external file. Remove the legacy token only after a verified cutover; migration backups currently may contain `.env` and require a separate evidence-aware cleanup.

## Rotation

Configure expected ID/username first, then run:

```console
sudo /opt/cocbot/.venv/bin/python /opt/cocbot/scripts/rotate_telegram_token.py \
  --project-dir /opt/cocbot --secret-file /etc/cocbot/cocbot.env
```

The token is read by a hidden prompt, never an argument. The script validates identity, removes a webhook without dropping pending updates, atomically replaces the file without a plaintext backup, preserves owner/group/mode, restarts only `cocbot`, checks it is active, and prints fingerprints only.

If validation fails before replacement, nothing changes. If restart fails after replacement, do **not** paste either token into a command. Restore service using a new BotFather-issued token through the same root-only editor/prompt procedure, verify the baseline and inspect `journalctl -u cocbot`; revoking the failed new token is safer than retaining a plaintext rollback copy.
