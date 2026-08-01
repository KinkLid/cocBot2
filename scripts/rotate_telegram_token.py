#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


class RotationError(RuntimeError):
    def __init__(self, message: str, *, secret_replaced: bool = False) -> None:
        super().__init__(message)
        self.secret_replaced = secret_replaced


def _service_active() -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", "cocbot"],
        check=False,
    ).returncode == 0


def _read_state(path: Path) -> dict:
    try:
        import json

        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


async def rotate(project: Path, secret_file: Path) -> None:
    if os.geteuid() != 0:
        raise RotationError("must be run as root")
    if not secret_file.exists():
        raise RotationError(f"secret file does not exist: {secret_file}")

    sys.path.insert(0, str(project))
    os.chdir(project)
    from aiogram import Bot
    from app.config.settings import Settings
    from app.security.audit import JsonlAudit, fingerprint, utc_now

    settings = Settings()
    baseline = settings.load_yaml_config().telegram_security
    if baseline.expected_bot_id is None or baseline.expected_username is None:
        raise RotationError("expected bot ID and username must be configured")

    old_text = secret_file.read_text(encoding="utf-8")
    old_token = next(
        (line.split("=", 1)[1].strip() for line in old_text.splitlines() if line.startswith("BOT_TOKEN=")),
        "",
    )
    if not old_token:
        raise RotationError("BOT_TOKEN entry not found; no changes made")

    old_audit = JsonlAudit(settings.security_audit_file, old_token)
    old_audit.write(
        "token_rotation_started",
        result="validation_pending",
        old_token_fingerprint=fingerprint(old_token),
    )

    new_token = getpass.getpass("New Telegram token from BotFather: ").strip()
    if not new_token:
        raise RotationError("empty token")
    if new_token == old_token:
        raise RotationError("new token equals current token")

    bot = Bot(new_token)
    try:
        me = await bot.get_me()
        username = (me.username or "").lower()
        if me.id != baseline.expected_bot_id or username != baseline.expected_username.lstrip("@").lower():
            raise RotationError("new token identity does not match baseline")
        await bot.delete_webhook(drop_pending_updates=False)
        if (await bot.get_webhook_info()).url:
            raise RotationError("new token still has an active webhook")
    except RotationError:
        raise
    except Exception as exc:
        raise RotationError(f"new token validation failed ({type(exc).__name__})") from None
    finally:
        await bot.session.close()

    old_audit.write(
        "token_rotation_validated",
        result="new_identity_verified",
        bot_id=me.id,
        new_token_fingerprint=fingerprint(new_token),
    )

    lines = [
        f"BOT_TOKEN={new_token}" if line.startswith("BOT_TOKEN=") else line
        for line in old_text.splitlines()
    ]
    stat = secret_file.stat()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{secret_file.name}.", dir=secret_file.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.chmod(temporary, stat.st_mode & 0o777)
        os.replace(temporary, secret_file)
        directory_fd = os.open(secret_file.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)

    new_audit = JsonlAudit(settings.security_audit_file, new_token)
    new_audit.write(
        "token_rotated",
        result="secret_replaced",
        bot_id=me.id,
        old_token_fingerprint=fingerprint(old_token),
        new_token_fingerprint=fingerprint(new_token),
    )

    rotation_started = datetime.now(UTC)
    try:
        subprocess.run(["systemctl", "restart", "cocbot"], check=True)
    except subprocess.CalledProcessError as exc:
        new_audit.write(
            "token_rotation_failed",
            severity="CRITICAL",
            result="secret_replaced_service_restart_failed",
            bot_id=me.id,
            error_class=type(exc).__name__,
        )
        raise RotationError("service restart failed after secret replacement", secret_replaced=True) from None

    deadline = time.monotonic() + 35
    observed_state: dict = {}
    while time.monotonic() < deadline:
        if _service_active():
            observed_state = _read_state(Path(settings.security_state_file))
            check_time_raw = observed_state.get("last_successful_security_check")
            try:
                check_time = datetime.fromisoformat(check_time_raw) if isinstance(check_time_raw, str) else None
                if check_time is not None and check_time.tzinfo is None:
                    check_time = check_time.replace(tzinfo=UTC)
            except ValueError:
                check_time = None
            if (
                observed_state.get("token_fingerprint") == fingerprint(new_token)
                and observed_state.get("observed_bot_id") == me.id
                and check_time is not None
                and check_time.astimezone(UTC) >= rotation_started
            ):
                break
        await asyncio.sleep(1)
    else:
        new_audit.write(
            "token_rotation_failed",
            severity="CRITICAL",
            result="secret_replaced_postcheck_failed",
            bot_id=me.id,
            service_active=_service_active(),
            observed_token_fingerprint=observed_state.get("token_fingerprint"),
            expected_token_fingerprint=fingerprint(new_token),
        )
        raise RotationError(
            "post-rotation service identity/security heartbeat was not confirmed",
            secret_replaced=True,
        )

    verify_bot = Bot(new_token)
    try:
        if (await verify_bot.get_webhook_info()).url:
            raise RotationError("webhook became active after service restart", secret_replaced=True)
    finally:
        await verify_bot.session.close()

    new_audit.write(
        "token_rotation_completed",
        result="identity_webhook_polling_verified",
        bot_id=me.id,
        completed_at=utc_now(),
    )
    print(
        f"Token rotated and verified: {fingerprint(old_token)} -> {fingerprint(new_token)}; "
        "cocbot is active, identity heartbeat matches, webhook is empty"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely rotate the primary Telegram token (prompt only; never a CLI argument)"
    )
    parser.add_argument("--project-dir", default="/opt/cocbot")
    parser.add_argument("--secret-file", default="/etc/cocbot/cocbot.env")
    args = parser.parse_args()
    try:
        asyncio.run(rotate(Path(args.project_dir).resolve(), Path(args.secret_file).resolve()))
        return 0
    except RotationError as exc:
        if exc.secret_replaced:
            print(
                f"rotation failed AFTER the secret file was replaced ({type(exc).__name__}); "
                "do not restore the compromised token; inspect systemctl/journal and docs/token_rotation.md",
                file=sys.stderr,
            )
        else:
            print(
                f"rotation aborted before secret replacement ({type(exc).__name__}); no token change was made",
                file=sys.stderr,
            )
        return 1
    except Exception as exc:
        print(f"rotation failed ({type(exc).__name__}); inspect docs/token_rotation.md", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
