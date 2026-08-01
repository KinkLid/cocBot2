#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path


async def rotate(project: Path, secret_file: Path) -> None:
    if os.geteuid() != 0:
        raise RuntimeError("must be run as root")
    sys.path.insert(0, str(project))
    os.chdir(project)
    from aiogram import Bot
    from app.config.settings import Settings
    from app.security.audit import JsonlAudit, fingerprint

    settings = Settings()
    baseline = settings.load_yaml_config().telegram_security
    if baseline.expected_bot_id is None or baseline.expected_username is None:
        raise RuntimeError("expected bot ID and username must be configured")
    new_token = getpass.getpass("New Telegram token from BotFather: ").strip()
    if not new_token:
        raise RuntimeError("empty token")
    bot = Bot(new_token)
    try:
        me = await bot.get_me()
        if me.id != baseline.expected_bot_id or me.username.lower() != baseline.expected_username.lstrip("@").lower():
            raise RuntimeError("new token identity does not match baseline")
        await bot.delete_webhook(drop_pending_updates=False)
        if (await bot.get_webhook_info()).url:
            raise RuntimeError("new token still has an active webhook")
    except Exception as exc:
        raise RuntimeError(f"new token validation failed ({type(exc).__name__})") from None
    finally:
        await bot.session.close()

    old_text = secret_file.read_text(encoding="utf-8")
    old_token = next((line.split("=", 1)[1] for line in old_text.splitlines() if line.startswith("BOT_TOKEN=")), "")
    lines = [f"BOT_TOKEN={new_token}" if line.startswith("BOT_TOKEN=") else line for line in old_text.splitlines()]
    if not old_token:
        raise RuntimeError("BOT_TOKEN entry not found; no changes made")
    stat = secret_file.stat()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{secret_file.name}.", dir=secret_file.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush(); os.fsync(stream.fileno())
        os.chown(temporary, stat.st_uid, stat.st_gid); os.chmod(temporary, stat.st_mode & 0o777)
        os.replace(temporary, secret_file)
    finally:
        temporary.unlink(missing_ok=True)
    audit = JsonlAudit(settings.security_audit_file, new_token)
    audit.write("token_rotated", result="secret_replaced", bot_id=me.id, old_token_fingerprint=fingerprint(old_token), new_token_fingerprint=fingerprint(new_token))
    subprocess.run(["systemctl", "restart", "cocbot"], check=True)
    subprocess.run(["systemctl", "is-active", "--quiet", "cocbot"], check=True)
    print(f"Token rotated: {fingerprint(old_token)} -> {fingerprint(new_token)}; cocbot is active")


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely rotate the primary Telegram token (token is prompted, never accepted as an argument)")
    parser.add_argument("--project-dir", default="/opt/cocbot")
    parser.add_argument("--secret-file", default="/etc/cocbot/cocbot.env")
    args = parser.parse_args()
    try:
        asyncio.run(rotate(Path(args.project_dir).resolve(), Path(args.secret_file).resolve()))
        return 0
    except Exception as exc:
        print(f"rotation failed safely ({type(exc).__name__}); see docs/token_rotation.md", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
