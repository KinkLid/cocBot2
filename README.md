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

1. синхронизирует код на сервер (с `rsync --delete` только для кода, при этом защищает на сервере `.env`, `config.yaml`, `logs/`, `data/`, `exports/`)
2. создает `.venv`, если нужно
3. ставит production-зависимости
4. применяет `alembic upgrade head`
5. устанавливает/обновляет systemd unit `cocbot.service`
6. выполняет `systemctl enable cocbot`
7. выполняет `systemctl restart cocbot`

### Где лежат конфиги

- `${PROJECT_DIR}/.env`
- `${PROJECT_DIR}/config.yaml`

`.env` и `config.yaml` — runtime-конфиги, они не должны храниться в git.

Deploy-скрипт сохраняет серверные `.env` и `config.yaml` (и runtime-директории `logs/`, `data/`, `exports/`), не удаляет их и не перезаписывает при `rsync --delete`.

При самом первом install, если файлов нет, но есть `.env.example`/`config.example.yaml`, они будут скопированы автоматически.
На повторных deploy/update отсутствие `.env` или `config.yaml` считается ошибкой: скрипт завершится с понятным сообщением и не создаст дефолтный конфиг молча.


### Деплой прямо на сервере (без локального rsync/scp)

Если вы уже на сервере в папке проекта, можно развернуть одной командой:

```bash
./scripts/deploy_local.sh
```

Скрипт корректно работает даже если запускать его из `scripts/` (например `cd scripts && ./deploy_local.sh`).

Или явно указать путь:

```bash
./scripts/deploy_local.sh /opt/cocbot
```

### Обновление с GitHub + переразворот одной командой

Если в удаленном репозитории есть изменения, выполните на сервере:

```bash
./scripts/update_from_git.sh
```

Скрипт автоматически делает `git fetch`, затем принудительно синхронизирует рабочую копию с `origin/<текущая_ветка>` через `git reset --hard`, после чего запускает полный server-side deploy (`venv`, зависимости, миграции, systemd restart).

> Важно: локальные незакоммиченные изменения в репозитории на сервере будут удалены.

### Проверка статуса и управление

```bash
systemctl status cocbot --no-pager
journalctl -u cocbot -f
systemctl restart cocbot
```


## Recovery Telegram-привязок из JSON-экспорта

Если потерялась SQLite-база (или ее часть), можно восстановить только пользовательские привязки (`telegram_users`, `player_accounts`, `telegram_player_links`) из JSON-экспорта текущего цикла.

Dry-run (только расчет изменений, без записи в БД):

```bash
python scripts/recover_links_from_export.py /path/to/current_cycle_export.json --dry-run
```

Реальное восстановление (upsert/reconcile без очистки таблиц):

```bash
python scripts/recover_links_from_export.py /path/to/current_cycle_export.json
```

Скрипт идемпотентный: повторный запуск не создает дубли, пропускает игроков без `telegram_id`, логирует конфликты существующих связей и не удаляет старые данные.

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
- deploy скрипты: `scripts/deploy_remote.sh`, `scripts/install_on_server.sh`
- миграции: `alembic/`
- тесты: `tests/`
