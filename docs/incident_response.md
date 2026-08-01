# Telegram incident response

## Classification and evidence

Use **Confirmed** only for observed audit/state/journal facts, **Likely** for a bounded inference, **Potentially affected** for users or updates in the window, **Unknown** for unavailable facts, and **Cannot be determined from Telegram Bot API** for caller IPs, call history, and the exact messages delivered elsewhere.

1. Treat any webhook/profile mismatch as continuing token compromise even after auto-repair. Rotate through BotFather; auto-repair does not close the incident.
2. Preserve `logs/security-audit.jsonl*`, `logs/update-audit.jsonl*`, `data/security-state.json`, `journalctl -u cocbot`, Git revision, systemd unit/overrides, process/network snapshots, and old deployment/backups. Do not copy secrets into tickets.
3. Generate a sanitized report: `sudo -u cocbot /opt/cocbot/.venv/bin/python /opt/cocbot/scripts/incident_report.py`.
4. The likely window starts after the last known empty-webhook check and ends at detection. Registration state events identify sessions our polling saw. A registration performed wholly while the hostile webhook was active may be entirely invisible locally.
5. Inspect successful/failed SSH logins, `authorized_keys`, sudo logs, cron, timers, services, unknown processes/connections, CI variables, Docker configuration, shell/editor histories, `/opt/cocbot-prev-*`, archives and backup permissions. Never delete evidence before capture.

## Manual server hardening runbook

Use key-only SSH, an individual sudo user, and (where operationally safe) disable direct root/password login. Review keys, enable fail2ban, unattended security updates, a least-privilege firewall and auditd. Review cron/systemd timers and outbound connections. These changes are deliberately not automated by this repository because a blind SSH/firewall change can lock out operators. After token rotation and evidence preservation, securely remove obsolete secret copies and tighten backup access.

Webhook check is performed by the monitor; inspect sanitized audit rather than manually embedding a token in `curl`. Profile baseline is in `config.yaml`. Remember: gaps and pending counts are estimates, not proof that a specific message was stolen.
