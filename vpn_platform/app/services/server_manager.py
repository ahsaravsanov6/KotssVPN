"""
app/services/server_manager.py
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
        return self.list_active()

    def add_server(self, **fields) -> ServerConfig:
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
        server = self._servers.get(server_id)
        if not server:
            raise ValueError(f"Сервер с id={server_id!r} не найден")

        if port is not None:
            server.port = port
        if sni:
            server.sni = sni
        if reality_public_key:
            server.reality_public_key = reality_public_key
        if reality_short_id is not None:
            server.reality_short_id = reality_short_id
        if flow:
            server.flow = flow
        if fingerprint:
            server.fingerprint = fingerprint

        save_all(self._servers)
        return server
