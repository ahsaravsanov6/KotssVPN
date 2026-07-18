"""
app/services/server_manager.py

Отвечает ТОЛЬКО на вопрос "какие сервера существуют и какие из них
активны". Раньше ходил в БД через ServerRepository — теперь сервера не
в БД (см. app/servers_config.py), поэтому ServerManager вообще не
принимает Session и не зависит от транзакции запроса. Это осознанно:
изменение списка серверов не должно быть завязано на коммит/роллбэк
той же транзакции, что и, скажем, добавление устройства.
"""

from app.servers_config import ServerConfig, ServerStatus, load_all, save_all


class ServerManager:
    def __init__(self) -> None:
        self._servers = load_all()

    def list_all(self) -> list[ServerConfig]:
        return sorted(self._servers.values(), key=lambda s: s.priority)

    def list_active(self) -> list[ServerConfig]:
        return [s for s in self.list_all() if s.is_active]

    def get_by_id(self, server_id: str) -> ServerConfig | None:
        return self._servers.get(server_id)

    def pick_servers_for_new_device(self) -> list[ServerConfig]:
        """
        Правило выбора серверов при добавлении НОВОГО устройства. По
        умолчанию — все активные сервера платформы (каждое устройство
        сразу получает доступ ко всей сети). При необходимости
        пер-тарифных пулов серверов меняется только этот метод.
        """
        return self.list_active()

    def add_server(self, **fields) -> ServerConfig:
        """
        Единственная операция записи, оставшаяся в коде — используется
        ТОЛЬКО migrations/migrate_from_legacy.py как часть одноразового
        переноса данных, чтобы не требовать от администратора вручную
        писать первую запись servers.yaml до миграции. Для повседневного
        добавления серверов используйте редактирование файла напрямую
        (см. docstring app/servers_config.py) — отдельного API/CLI под
        это специально не сделано, чтобы не дублировать `nano`.
        """
        server_id = fields.get("id")
        if not server_id:
            raise ValueError("Поле 'id' обязательно (уникальный слаг сервера, например 'nl-1')")
        if server_id in self._servers:
            raise ValueError(f"Сервер с id={server_id!r} уже существует")

        fields.setdefault("status", ServerStatus.ACTIVE.value)
        server = ServerConfig(**fields)
        self._servers[server.id] = server
        save_all(self._servers)
        return server

    def apply_technical_config(
        self,
        server_id: str,
        *,
        port: int | None = None,
        sni: str | None = None,
        reality_public_key: str | None = None,
        reality_short_id: str | None = None,
        flow: str | None = None,
        fingerprint: str | None = None,
    ) -> ServerConfig:
        """
        Вторая (и последняя) операция записи, оставшаяся в API — в отличие
        от create/status/delete (сознательно убраны, см. add_server
        docstring), эта не дублирует `nano`, а устраняет реальный источник
        ошибок: ручной перенос длинных base64-ключей Reality с панели в
        файл. Используется POST /admin/servers/{id}/autofill, который
        сначала читает эти значения с панели через
        PanelProvider.fetch_technical_config().

        Каждое поле обновляется только если передано непустым — так
        частичный ответ панели (например, flow не удалось определить,
        потому что на инбаунде ещё нет ни одного клиента) не затирает уже
        существующее значение чем-то пустым.
        """
        server = self._servers.get(server_id)
        if not server:
            raise ValueError(f"Сервер с id={server_id!r} не найден")

        if port is not None:
            server.port = port
        if sni:
            server.sni = sni
        if reality_public_key:
            server.reality_public_key = reality_public_key
        if reality_short_id is not None:  # пустая строка — валидное значение (Reality допускает short_id="")
            server.reality_short_id = reality_short_id
        if flow:
            server.flow = flow
        if fingerprint:
            server.fingerprint = fingerprint

        save_all(self._servers)
        return server
