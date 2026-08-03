# VPN Platform (v2, per-device numbering) — multi-server architecture

Каркас архитектуры, отделяющий бизнес-логику от 3X-UI, теперь подключённый
к боту (`public_html/bot_vpn`) как основной источник подписки. Подробности
решений — в `docs/ARCHITECTURE.md` (см. addendum наверху про нумерацию
устройств).

## Быстрый старт (dev)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# заполните BOT_TOKEN, API_ADMIN_KEY, SUBSCRIPTION_PUBLIC_DOMAIN, SERVERS_FILE

alembic upgrade head   # применит 0001_initial + 0002_device_numbering

uvicorn app.api.main:app --reload --port 8090
```

`GET http://127.0.0.1:8090/healthz` должен вернуть `{"status": "ok"}`.

### Добавление сервера

См. `docs/ARCHITECTURE.md`. Кратко: правьте `servers.yaml` вручную,
затем `POST /admin/servers/{id}/health` и `POST /admin/servers/{id}/autofill`.

### Подключение бота (public_html/bot_vpn)

В `public_html/bot_vpn/.env`:

```
PLATFORM_API_URL=http://127.0.0.1:8090
PLATFORM_API_KEY=<то же значение, что API_ADMIN_KEY здесь>
```

Бот теперь получает подписку ИМЕННО отсюда (см.
`public_html/bot_vpn/bot/services/api_client.py`) — старый
`public_html/backend` больше ботом не используется (оставлен в репозитории
как справочный код, см. `public_html/backend/README_LEGACY.md`).

### Что изменилось по сравнению с предыдущей ревизией

- Каждое устройство получает **свою** персональную ссылку подписки
  (`GET /sub/{token}/{device_id}`), как и в исходном одно-серверном боте —
  просто теперь эта ссылка охватывает несколько серверов сразу.
- Имя клиента в каждой панели 3X-UI строится как
  `"{telegram_id}_device_{N}"`, где `N` — реальный порядковый номер
  устройства пользователя (1, 2, 3, ...), а не случайный технический id.
- Добавлен `POST /internal/devices/buy_slot` — докупка доп. места под
  устройство (был в исходном `public_html/backend`, отсутствовал в
  предыдущей ревизии платформы).

## Структура

```
app/
  config.py                 # только параметры платформы, НЕ серверов
  servers_config.py          # ServerConfig — dataclass + load/save YAML
  db/
    base.py
    models/                 # User (+next_device_number), Device (+device_number), DeviceServerAccess
    repositories/
  providers/
    base.py
    xui/client.py             # remote_id_for = "{telegram_id}_device_{N}"
    registry.py
  services/
    user_service.py
    device_service.py         # присваивает device_number, лимит устройств
    server_manager.py
    provisioning_service.py
    subscription_generator.py
    subscription_service.py    # build_subscription (все устройства) + build_device_subscription (одно)
  utils/vless.py
  api/
    main.py
    routers/
      subscription.py          # GET /sub/{token} и /sub/{token}/{device_id}
      internal.py               # /internal/* — для бота, включая /devices/buy_slot
      admin_servers.py
alembic/
  versions/
    0001_initial.py
    0002_device_numbering.py    # добавляет device_number/next_device_number
migrations/migrate_from_legacy.py
scripts/
  resync_pending_access.py
  sync_devices_to_active_servers.py
tests/
  test_device_numbering.py      # новый: нумерация устройств + remote_id_for
```
