# Clash of Clans Clan Telegram Bot

Production-like Telegram-бот для мониторинга клана Clash of Clans.

## Что умеет

- регистрация через официальный `player token`
- привязка нескольких игровых аккаунтов к одному Telegram-пользователю
- мониторинг состава клана
- мониторинг обычных КВ и ЛВК
- сохранение ростеров, атак, нарушений
- уведомления админам о нарушениях и возвратах игроков
- статистика по игроку и по клану
- JSON-экспорт
- tail логов и скачивание лог-файла
- dev-отчет по отдельной формуле вклада

## Стек

- Python 3.12
- aiogram 3
- SQLite
- SQLAlchemy 2.x
- Alembic
- APScheduler
- pytest
- Docker / Docker Compose

## Быстрый старт

```bash
cp .env.example .env
cp config.example.yaml config.yaml
# заполнить токены и admin_telegram_ids
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[dev]
alembic upgrade head
python -m app.main
```

## Тесты

```bash
PYTHONPATH=. pytest -q
```

## Docker Compose

```bash
docker compose up -d --build
```

## Конфигурация

### `.env`

- `BOT_TOKEN`
- `CLASH_API_TOKEN`
- `DATABASE_URL`
- `DATABASE_URL_SYNC` (опционально, отдельный sync URL для Alembic)
- `CONFIG_PATH`
- `LOG_FILE`

### `config.yaml`

- `main_clan_tag`
- `admin_telegram_ids`
- `clan_chat_url`
- `polling.*`
- `log_level`

## Важная деталь по времени атаки

Clash of Clans API не дает удобный серверный timestamp атаки для полноценной исторической фиксации “точного времени удара” в той форме, которая нужна этому боту. Поэтому проект хранит `observed_at` — момент, когда бот впервые увидел атаку.

## Файлы

- подробный обзор проекта: `PROJECT_GUIDE.md`
- systemd unit: `deploy/systemd/clanbot.service`
- миграции: `alembic/`
- тесты: `tests/`
