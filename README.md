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

## Автоматический раскат на Ubuntu (venv + systemd)

### Что должно быть установлено на сервере

- Ubuntu с `systemd`
- `python3.12`, `python3.12-venv`
- `tar`

### Что должно быть установлено локально

- `ssh`
- `tar`
- `rsync` (предпочтительно) или `scp`

### One-command deploy

```bash
chmod +x scripts/deploy_remote.sh
./scripts/deploy_remote.sh root@1.2.3.4 /opt/cocbot
```

Скрипт автоматически:

1. синхронизирует код на сервер (с исключением `.venv`, `.git`, `logs`, `data` и т.д.)
2. создает `.venv`, если нужно
3. ставит production-зависимости
4. применяет `alembic upgrade head`
5. устанавливает/обновляет systemd unit `cocbot.service`
6. выполняет `systemctl enable cocbot`
7. выполняет `systemctl restart cocbot`

### Где лежат конфиги

- `${PROJECT_DIR}/.env`
- `${PROJECT_DIR}/config.yaml`

Если файлов нет, но есть `.env.example`/`config.example.yaml`, они будут скопированы автоматически.
Существующие `.env` и `config.yaml` не перезаписываются.


### Деплой прямо на сервере (без локального rsync/scp)

Если вы уже на сервере в папке проекта, можно развернуть одной командой:

```bash
./scripts/deploy_local.sh
```

Или явно указать путь:

```bash
./scripts/deploy_local.sh /opt/cocbot
```

### Обновление с GitHub + переразворот одной командой

Если в удаленном репозитории есть изменения, выполните на сервере:

```bash
./scripts/update_from_git.sh
```

Скрипт автоматически делает `git fetch`, `git pull --ff-only` и затем повторно запускает полный server-side deploy (`venv`, зависимости, миграции, systemd restart).

### Проверка статуса и управление

```bash
systemctl status cocbot --no-pager
journalctl -u cocbot -f
systemctl restart cocbot
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
- шаблон systemd unit для deploy: `deploy/systemd/cocbot.service.template`
- legacy unit пример: `deploy/systemd/clanbot.service`
- deploy скрипты: `scripts/deploy_remote.sh`, `scripts/install_on_server.sh`
- миграции: `alembic/`
- тесты: `tests/`
