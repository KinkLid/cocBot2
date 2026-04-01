# 1. Архитектура

Проект построен по слоям:

- `clients` — HTTP-клиент Clash of Clans API.
- `repositories` — доступ к БД без бизнес-логики.
- `domain` — чистые правила: нарушения, периоды, dev-вклад.
- `services` — бизнес-операции: регистрация, синхронизация состава, синхронизация войн, статистика, экспорт, чат, логи.
- `bot` — aiogram 3 routers, клавиатуры, FSM, middleware.
- `jobs` — APScheduler-задачи для периодического опроса.
- `models/db` — SQLAlchemy 2.x, SQLite, Alembic.

Поток данных:

1. Планировщик запускает фоновые задачи.
2. `ClanSyncService` обновляет текущий состав, фиксирует выходы, возвраты, purge после полного цикла отсутствия.
3. `WarSyncService` синхронизирует обычные войны и ЛВК, сохраняет ростеры, атаки, нарушения, отправляет антидубль-уведомления админам.
4. `StatsService` строит пользовательские и админские отчеты по выбранному периоду.
5. `ExportService` формирует подробный JSON для дальнейшего анализа.
6. `LogService` отдает tail и полный лог-файл.

Идемпотентность обеспечивается:

- уникальным `war_uid`;
- уникальностью участника войны `(war_id, player_tag)`;
- уникальностью атаки `(war_id, attacker_tag, defender_tag, attack_order)`;
- уникальностью нарушения на `attack_id`;
- уникальностью уведомления `(admin_telegram_id, event_key)`.

Polling strategy:

- активные войны: каждые 90 секунд;
- состав клана: каждые 15 минут;
- housekeeping: каждый час.

Причина выбора: состав клана меняется заметно реже, а для нарушений в первые 12 часов нужен частый опрос, чтобы быстро зафиксировать новую атаку и минимизировать лаг между атакой и уведомлением.

# 2. Структура проекта

```text
app/
  bot/
    app.py
    handlers/
    keyboards/
    middlewares/
    states/
  clients/
  config/
  db/
  domain/
  jobs/
  models/
  repositories/
  schemas/
  services/
  utils/
  container.py
  main.py
alembic/
  versions/
tests/
deploy/systemd/
Dockerfile
docker-compose.yml
alembic.ini
.env.example
config.example.yaml
README.md
PROJECT_GUIDE.md
```

# 3. Схема БД

Основные таблицы:

- `telegram_users`
- `player_accounts`
- `telegram_player_links`
- `clan_membership_history`
- `wars`
- `war_participants`
- `attacks`
- `violations`
- `cycle_boundaries`
- `clan_settings`
- `admin_notification_history`
- `departed_players_archive`
- `return_events`

Ключевые связи:

- `telegram_users 1:N telegram_player_links`
- `player_accounts 1:N clan_membership_history`
- `wars 1:N war_participants`
- `wars 1:N attacks`
- `attacks 1:1 violations`

Ключевые индексы и ограничения:

- `player_accounts.player_tag UNIQUE`
- `wars.war_uid UNIQUE`
- `war_participants (war_id, player_tag) UNIQUE`
- `attacks (war_id, attacker_tag, defender_tag, attack_order) UNIQUE`
- `violations.attack_id UNIQUE`
- `admin_notification_history (admin_telegram_id, event_key) UNIQUE`
- `cycle_boundaries.source_key UNIQUE`

# 4. Все ключевые допущения

1. Официальный API не отдает удобный для прямого использования timestamp атаки в том виде, который нужен для истории “фактического времени удара” в БД. Поэтому проект хранит `observed_at` — момент, когда бот впервые увидел атаку при опросе API.
2. Правило первых 12 часов проверяется по `observed_at`. Для уменьшения погрешности активные войны опрашиваются часто.
3. “Текущий цикл” = от последней завершенной границы ЛВК до текущего времени, если следующая граница еще не завершилась.
4. “Прошлый цикл” = между двумя последними завершенными границами ЛВК.
5. В статистику клана попадают только текущие участники клана.
6. При полном purge игрок удаляется из активных таблиц, а в архиве остается минимальный след для детекта возврата.
7. Привязка Telegram → player tag хранится отдельно от активной боевой истории, чтобы архитектура не зависела от структуры войн.
8. ЛВК хранится как набор отдельных войн с привязкой к `league_group_id` и `cwl_season`.

# 5. Подробный тест-план

Покрытые группы:

- регистрация и валидация player token;
- множественные аккаунты и защита от дублей;
- синхронизация состава, выходы, игнорирование в статистике, purge, возвраты;
- обычные войны и ЛВК;
- участие по ростеру;
- сохранение атак;
- звезды и нарушения;
- защита от дублей уведомлений;
- статистика по текущему циклу, прошлому циклу и кастомному периоду;
- ранжирование игроков и админская сортировка;
- JSON-экспорт;
- ссылка на чат;
- логирование;
- проверка админских прав;
- FSM-сценарии;
- smoke/e2e кнопок.

# 6. Полный набор тестов

Реализовано 40 тестов в файлах:

- `tests/test_registration.py`
- `tests/test_membership.py`
- `tests/test_wars.py`
- `tests/test_stats.py`
- `tests/test_export_and_admin.py`
- `tests/test_fsm.py`
- `tests/test_smoke.py`

Фактический статус локального прогона в контейнере: `40 passed`.

# 7. Реализация

Ключевые точки входа:

- запуск бота: `python -m app.main`
- планировщик: `app/jobs/scheduler.py`
- регистрация: `app/services/registration.py`
- состав: `app/services/clan_sync.py`
- войны: `app/services/war_sync.py`
- статистика: `app/services/stats.py`
- экспорт: `app/services/export.py`
- dev-вклад: `app/services/dev_contribution.py`

# 8. Dockerfile

См. `Dockerfile` в корне проекта.

# 9. docker-compose.yml

См. `docker-compose.yml` в корне проекта.

# 10. .env.example

См. `.env.example`.

# 11. config.example.yaml

См. `config.example.yaml`.

# 12. Alembic-миграции или init-db

В проекте есть:

- `alembic.ini`
- `alembic/env.py`
- `alembic/versions/0001_initial.py`

Применение:

```bash
alembic upgrade head
```

# 13. README.md

См. `README.md`.

# 14. Инструкция запуска через Docker Compose

```bash
cp .env.example .env
cp config.example.yaml config.yaml
# заполнить BOT_TOKEN, CLASH_API_TOKEN, admin_telegram_ids, main_clan_tag
mkdir -p data logs exports
docker compose up -d --build
docker compose logs -f
```

# 15. Инструкция запуска через venv + systemd

```bash
sudo mkdir -p /opt/clanbot
sudo chown -R $USER:$USER /opt/clanbot
cp -R . /opt/clanbot
cd /opt/clanbot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[dev]
cp .env.example .env
cp config.example.yaml config.yaml
alembic upgrade head
sudo cp deploy/systemd/clanbot.service /etc/systemd/system/clanbot.service
sudo systemctl daemon-reload
sudo systemctl enable clanbot
sudo systemctl start clanbot
sudo systemctl status clanbot
```

# 16. Примеры интерфейсных сообщений

Пользовательская статистика:

```text
👤 Alpha #P2
└ 👤 @tester • 🆔 100 • 🗓 2026-01-28 01:36

📆 Период: 2026-03-06 — 2026-04-01
⚔️ Войн: 2
🗡 Атак: 2
⭐ Звёзд: 5
🏅 Место в клане: 1
```

Уведомление о нарушении:

```text
🚨 Нарушение атаки
Игрок: Alpha #P2
Война: КВ
Время фиксации: 2026-04-01 11:00:00 UTC
Нарушение №1
Цель: Enemy2 #E2
Позиция игрока: 12
Позиция цели: 5
Причина: Атака по сопернику выше своей позиции в первые 12 часов
```

Возврат игрока:

```text
🔁 Игрок вернулся в клан: Alpha #P2
```

Пример структуры логов:

```text
2026-04-01 12:00:00 | INFO | app.jobs.scheduler | Housekeeping tick
2026-04-01 12:01:30 | INFO | app.services.war_sync | Violation recorded for attack 15
2026-04-01 12:15:00 | INFO | app.services.clan_sync | Player left clan: #P8
2026-04-05 10:00:00 | INFO | app.services.clan_sync | Return detected for #P2
```

Пример структуры JSON-выгрузки:

```json
{
  "period": {
    "start": "2026-03-06T00:00:00+00:00",
    "end": "2026-04-01T23:59:59+00:00"
  },
  "clan": {
    "tag": "#CLAN"
  },
  "players": [
    {
      "player_tag": "#P2",
      "player_name": "Alpha",
      "wars": 2,
      "attacks": 2,
      "stars": 5,
      "violations": 0,
      "participation": [
        {
          "war_uid": "regular:#CLAN:#ENEMY:20260401T100000.000Z:0",
          "war_type": "regular",
          "roster_position": 12,
          "attacks": []
        }
      ]
    }
  ]
}
```

# 17. Список ограничений

1. `observed_at` — это момент обнаружения атаки ботом, а не гарантированное серверное время удара.
2. FSM-хранилище сейчас in-memory. Для одного процесса этого достаточно, но при горизонтальном масштабировании лучше вынести FSM в Redis.
3. SQLite подходит для одного экземпляра и умеренной нагрузки. Для роста проекта лучше переходить на PostgreSQL.
4. Сейчас slash-команды не используются как основной UX, но `/start` оставлен вспомогательно.
5. JSON-экспорт сейчас делается файлом на диск и отправляется из локального каталога `exports`.

# 18. Идеи дальнейшего развития

1. Перевести FSM в Redis.
2. Добавить webhook-режим.
3. Перейти на PostgreSQL для больших кланов и нескольких кланов.
4. Добавить richer admin dashboards и графики.
5. Развести экспорт текущий / прошлый / кастомный отдельными кнопками с inline-веткой.
6. Добавить резервное копирование БД и логов.
7. Реализовать расширенный dev-вклад с несколькими формулами и A/B-сравнением.
