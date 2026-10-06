from __future__ import annotations

import asyncio
import hmac
import socket
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from amqtt.broker import Broker
from amqtt.plugins.base import BaseAuthPlugin
from amqtt.session import Session


class CredenciaisLocaisPlugin(BaseAuthPlugin):

    @dataclass
    class Config:
        username: str = ""
        password: str = field(default="", repr=False)

    async def authenticate(self, *, session: Session) -> bool:
        if not session.username or not session.password:
            return False
        return (
            hmac.compare_digest(session.username.encode("utf-8"), self.config.username.encode("utf-8"))
            and hmac.compare_digest(session.password.encode("utf-8"), self.config.password.encode("utf-8"))
        )


def porta_livre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@asynccontextmanager
async def broker_local(port: int = 1883, *, username: str = "", password: str = ""):
    if bool(username) != bool(password):
        raise ValueError("Preencha MQTT_USERNAME e MQTT_PASSWORD juntos, ou deixe ambos vazios.")
    if username:
        plugins = {"monitoramento.broker.CredenciaisLocaisPlugin": {"username": username, "password": password}}
    else:
        plugins = {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}}

    broker = Broker({
        "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
        "plugins": plugins,
    })
    await broker.start()
    try:
        yield broker
    finally:
        await broker.shutdown()


async def executar_broker(port: int, *, username: str = "", password: str = "") -> None:
    async with broker_local(port, username=username, password=password):
        authentication = "usuário e senha obrigatórios" if username else "sem autenticação"
        print(f"Broker MQTT local em 127.0.0.1:{port} ({authentication}). Ctrl+C para encerrar.", flush=True)
        await asyncio.Event().wait()
