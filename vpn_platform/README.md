# VPN Platform (v2) — multi-server architecture

Каркас новой архитектуры, отделяющий бизнес-логику от 3X-UI. Подробное
объяснение решений — в `docs/ARCHITECTURE.md`. Здесь — как запустить и
как встраивать поверх текущего репозитория `KotssVPN`.

## Быстрый старт (dev)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# заполните BOT_TOKEN, API_ADMIN_KEY, SUBSCRIPTION_PUBLIC_DOMAIN, SERVERS_FILE
# (путь к YAML-файлу со списком серверов — см. docs/ARCHITECTURE.md, раздел
# "Сервера — файл, не таблица БД"); для dev DATABASE_URL можно оставить sqlite

# Prod: схема БД (users/devices) управляется Alembic, не create_all
alembic upgrade head

# Dev-альтернатива (быстрый старт без Alembic, НЕ использовать в проде):
# python -c "from app.db.base import create_all_tables; create_all_tables()"

uvicorn app.api.main:app --reload --port 8090
```

`GET http://127.0.0.1:8090/healthz` должен вернуть `{"status": "ok"}`.

### Добавление первого (и любого следующего) сервера

Список серверов правится вручную — создайте/откройте файл по пути из
`SERVERS_FILE` и добавьте блок:

```bash
mkdir -p $(dirname /путь/из/SERVERS_FILE)
nano /путь/из/SERVERS_FILE
```

```yaml
servers:
  - id: primary            # уникальный слаг, не меняется после создания
    name: "Primary"
    country: "NL"
    address: your.domain.com
    sni: google.com
    reality_public_key: <reality_public_key>
    reality_short_id: <short_id>
    panel_base_url: "https://your-panel:2053"
    panel_username: admin
    panel_password: "***"
    inbound_id: 1
    status: active          # active | maintenance | disabled
    priority: 100            # меньше = выше в списке подписки
```

Сохраните, затем проверьте, что файл валиден и API его подхватил
(перезапуск не требуется — читается заново при каждом запросе):

```bash
curl http://127.0.0.1:8090/admin/servers -H "x-api-key: ВАШ_API_ADMIN_KEY"
```

И что креды/адрес панели рабочие — без побочных эффектов на самой панели:

```bash
curl -X POST http://127.0.0.1:8090/admin/servers/primary/health -H "x-api-key: ВАШ_API_ADMIN_KEY"
```

Эти два GET/POST — единственное, что осталось от управления серверами
через API; создание/статус/удаление сознательно не автоматизированы —
при ожидаемых единицах серверов это дублировало бы `nano`. Подробнее
о причине — в `docs/ARCHITECTURE.md`.

## Надёжность: что уже проверено и что нужно эксплуатировать

- **Инвариант "один UUID на устройство, одинаковый на всех его серверах"
  доказан не только тестом, но и живым e2e-прогоном** (регистрация →
  оплата → лимит устройств на 3-м/4-м устройстве → добавление второго
  сервера устройству → перевыпуск ключа конкретного устройства — не
  затрагивает остальные). `create_client` в `XUIProvider` не доверяет
  панели вслепую: после создания клиента читает его обратно и
  принудительно фиксирует UUID через `update`, если панель создала
  клиента с другим id — см. докстринг `app/providers/xui/client.py`.
- **Лимит устройств восстановлен и покрыт тестами** (`tests/test_device_service.py`):
  ровно `DEFAULT_MAX_DEVICES + user.extra_devices` устройств проходят,
  следующее получает `limit_reached=True` — без обращения к панели,
  проверка на уровне БД, как и в исходном проекте. `limitIp=1` на
  клиенте каждого устройства восстанавливает и техническое ограничение
  на панели.
- **Ретраи и постоянные сессии.** Каждый сервер держит одну переиспользуемую
  `httpx.AsyncClient`-сессию с логином под `asyncio.Lock` (без гонок при
  параллельных запросах) и ретраями с бэкоффом на 429/5xx и сетевые сбои.
- **Идемпотентность провижининга.** `grant_access`/`revoke_access`
  защищены локальной блокировкой на пару (user, server) + уникальным
  констрейнтом в БД — повторный вебхук от платёжки (частый случай у
  YooKassa/CryptoBot при ретраях доставки) не создаёт дублей и не роняет
  запрос.
- **`GET /admin/servers/{id}/health`** — неразрушающая проверка (логин +
  список инбаундов) сразу после добавления сервера, до того, как на него
  попытаются провижинить реального пользователя.
- **`scripts/resync_pending_access.py`** — гоняйте по крону раз в
  5-15 минут: подхватывает доступы, у которых `enabled=True` но
  `provisioned=False` (панель была временно недоступна в момент оплаты),
  и повторяет провижининг. Без этого такой пользователь рискует навсегда
  остаться без доступа к конкретному серверу.
- **Валидация входа.** Все `internal`/`admin` эндпоинты — на Pydantic-схемах
  (`app/api/schemas.py`), опечатка в теле запроса даёт понятную 422, а не
  тихий `None` где-то в середине бизнес-логики или 500 без объяснений.
- **Тесты.** `tests/` покрывает чистую логику без сети/БД (`pytest`):
  сборку `vless://`, генерацию тела подписки, свойство `subscription_status`.
  Запуск: `pytest tests/ -v`.
- **Единый обработчик исключений** в `app/api/main.py` гарантирует, что
  любая непойманная ошибка попадает в лог с полным traceback, а не
  теряется молча.

## План внедрения поверх существующего проекта (без простоя)

Репозиторий уже содержит рабочий бот + backend + analytics — их не
нужно выключать одномоментно. Рекомендуемая последовательность:

1. **Поднять новый API рядом со старым**, на отдельном порту/поддомене.
   Ничего в проде ещё не меняется.
2. **Прогнать `migrations/migrate_from_legacy.py`** с параметрами
   текущего единственного сервера (те же значения, что раньше сидели в
   `public_html/backend/config.py`: `XUI_BASE_URL`, `XUI_SUB_DOMAIN`,
   `XUI_PUBLIC_KEY` и т.д.). Старые per-device клиенты в 3X-UI при этом
   не трогаются — см. предупреждение в докстринге скрипта.
3. **Переключить бота** (`public_html/bot_vpn/bot/services/api_client.py`)
   на новые `internal`-эндпоинты: `register_user`, `get_account`,
   `buy_subscription`, `start_trial` теперь возвращают `sub_url` вместо
   конфига под конкретное устройство. Экраны `vpn.py`/`devices.py`
   постепенно заменяются одним экраном "Моя подписка" со ссылкой
   `/sub/<token>` и QR-кодом на неё — как это и требует новая модель
   (один линк на все сервера, а не ключ на устройство).
4. **Оплата** (`payment.py`, `webhook_server.py`) не меняется по
   транспорту (YooKassa/CryptoBot/Heleket остаются), меняется только
   вызов в конце: вместо `api_client.buy_subscription()` к старому
   backend — тот же метод, но к новому `internal/subscription/buy`,
   которое само вызывает `ProvisioningService`.
5. **Добавление второго сервера** — теперь просто: добавьте блок в
   `servers.yaml` (см. раздел "Добавление сервера" выше). Существующие
   пользователи ничего не почувствуют, пока вы явно не решите выдать им
   доступ (`SubscriptionService.add_server_to_device`) — например, как
   отдельную кнопку выбора страны в боте.
6. **`analytics/`** можно постепенно переориентировать с чтения
   `vpn_bot.db` на чтение новой БД платформы (`snapshot_users` теперь
   агрегирует по всем серверам, а не по одному) — это отдельная
   некритичная миграция, старый `bot_db_reader.py` можно оставить
   работать параллельно на старой БД сколько угодно, если легаси-бот
   ещё не выключен.
7. Когда метрики (снапшоты трафика в `analytics`) покажут отсутствие
   активности на старых per-device клиентах — вывести их из
   эксплуатации отдельной операцией, отключить старый backend.

## Структура

См. дерево и объяснение слоёв в `docs/ARCHITECTURE.md`. Коротко:

```
app/
  config.py                 # только параметры платформы, НЕ серверов
  servers_config.py          # ServerConfig — dataclass + load/save YAML, НЕ модель БД
  db/
    base.py                 # engine/session
    models/                 # User, Device, DeviceServerAccess (Server здесь больше нет)
    repositories/           # тонкий CRUD-слой над БД (не над серверами)
  providers/
    base.py                 # интерфейс PanelProvider (ABC), работает с Device+ServerConfig
    xui/client.py            # реализация для 3X-UI, limitIp=1 на клиента устройства
    registry.py              # panel_type -> provider
  services/
    user_service.py          # регистрация, триал, продление (даты подписки)
    device_service.py         # лимит устройств, добавление/удаление — ключевая логика
    server_manager.py         # список/выбор серверов — читает/пишет servers.yaml
    provisioning_service.py    # единственное место, дёргающее панели (per-device)
    subscription_generator.py  # сборка тела подписки — матрица устройство×сервер
    subscription_service.py    # оркестрация: token → user → devices → servers → payload
  utils/vless.py              # построение vless:// URI из ServerConfig+Device
  api/
    main.py                   # FastAPI app
    routers/
      subscription.py          # GET /sub/{token} — публично
      internal.py               # регистрация/оплата/устройства — для бота
      admin_servers.py           # только list + health-check; сам servers.yaml правится вручную
alembic/                       # версионирование СХЕМЫ БД (users/devices), НЕ серверов
  versions/0001_initial.py
migrations/migrate_from_legacy.py  # легаси Device 1-в-1 ложится в новую схему
scripts/
  resync_pending_access.py       # гонять по крону — самолечение зависшего провижининга
tests/                           # pytest — включая test_device_service.py на лимит устройств
```
