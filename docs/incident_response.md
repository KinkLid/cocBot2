# Telegram incident response

## Classification

Use **Confirmed** only for observed state/audit/journal facts, **Likely** for bounded inference, **Potentially affected** for users or updates in the time window, and **Cannot be determined from Telegram Bot API** for caller IPs, API-call history, and exact messages delivered elsewhere.

## Immediate actions

1. Treat any webhook, identity, or profile mismatch as continuing token compromise even after auto-repair.
2. Preserve `logs/security-audit.jsonl*`, `logs/update-audit.jsonl*`, `data/security-state.json`, `journalctl -u cocbot`, Git revision, systemd unit/overrides, process/network snapshots, and old deployments/backups.
3. Reissue the token through BotFather and use `scripts/rotate_telegram_token.py`.
4. Generate a sanitized report:

```console
sudo -u cocbot /opt/cocbot/.venv/bin/python \
  /opt/cocbot/scripts/incident_report.py
```

Pass `--incident-id` to select an older recorded incident. The report reads the state and both JSONL evidence streams, verifies version-2 hash-chain links, reports update IDs around the incident window, and summarizes registration-state events without message contents.

## Interpreting the report

The likely compromise window begins after `last_known_empty_before_incident` and ends no later than detection. The hostile delivery period may continue until removal. A registration performed entirely while another webhook was active may be invisible locally. Pending count and update-ID gaps are estimates, not proof that a particular message was received by an attacker.

The report keeps each webhook occurrence separate. Do not combine the first recovered update of one incident with a later incident.

## Server investigation

Inspect successful and failed SSH logins, `authorized_keys`, sudo logs, cron, timers, services, unknown processes/connections, CI variables, Docker configuration, shell/editor histories, old deployment directories, archives, and backup permissions. Never delete evidence before capture.

Use key-only SSH, individual sudo accounts, fail2ban, unattended security updates, a least-privilege firewall, and auditd where operationally safe. SSH/firewall changes remain manual because blind automation can lock out operators.
