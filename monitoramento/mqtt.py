from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from uuid import uuid4

import paho.mqtt.client as mqtt

from .config import Config

logger = logging.getLogger(__name__)


def novo_cliente(config: Config, role: str) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f"{role}-{uuid4().hex[:12]}", protocol=mqtt.MQTTv311)
    if config.mqtt_username:
        client.username_pw_set(config.mqtt_username, config.mqtt_password)
    if config.mqtt_tls:
        client.tls_set()
    client.reconnect_delay_set(min_delay=1, max_delay=15)
    return client


class ReceptorMQTT:
    def __init__(self, config: Config):
        self.config = config
        self.client = novo_cliente(config, "monitor")
        self.queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        self.ready = asyncio.Event()
        self.error: str | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def __aenter__(self):
        self.loop = asyncio.get_running_loop()

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code.is_failure:
                self.error = "Broker MQTT recusou a conexão."
                self.loop.call_soon_threadsafe(self.ready.set)
                return
            code, _ = client.subscribe(self.config.mqtt_topic, qos=1)
            if code != mqtt.MQTT_ERR_SUCCESS:
                self.error = "Não foi possível solicitar a assinatura MQTT."
                self.loop.call_soon_threadsafe(self.ready.set)

        def on_subscribe(client, userdata, mid, reason_codes, properties):
            if any(code.is_failure for code in reason_codes):
                self.error = "Broker MQTT recusou a assinatura."
            self.loop.call_soon_threadsafe(self.ready.set)

        def on_message(client, userdata, message):
            self.loop.call_soon_threadsafe(self.queue.put_nowait, (message.topic, bytes(message.payload)))

        def on_disconnect(client, userdata, flags, reason_code, properties):
            if reason_code.is_failure:
                if not self.ready.is_set():
                    self.error = "Broker MQTT recusou ou encerrou a conexão. Verifique usuário e senha."
                    self.loop.call_soon_threadsafe(self.ready.set)
                logger.warning("MQTT desconectado; o cliente tentará reconectar e refazer a assinatura.")

        self.client.on_connect = on_connect
        self.client.on_subscribe = on_subscribe
        self.client.on_message = on_message
        self.client.on_disconnect = on_disconnect
        self.client.connect_async(self.config.mqtt_host, self.config.mqtt_port, keepalive=30)
        self.client.loop_start()
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=self.config.timeout)
            if self.error:
                raise RuntimeError(self.error)
        except BaseException:
            await self.close()
            raise
        return self

    async def close(self) -> None:
        self.client.disconnect()
        await asyncio.to_thread(self.client.loop_stop)

    async def __aexit__(self, *args):
        await self.close()


def publicar_payloads(config: Config, messages: list[tuple[str, bytes]], interval: float = 0) -> None:
    client = novo_cliente(config, "simulador")
    connected = threading.Event()
    errors = []

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            errors.append("Broker MQTT recusou o simulador.")
        connected.set()

    def on_disconnect(client, userdata, flags, reason_code, properties):
        if not connected.is_set() and reason_code.is_failure:
            errors.append("Broker MQTT recusou ou encerrou a conexão do simulador. Verifique usuário e senha.")
            connected.set()

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    try:
        client.connect(config.mqtt_host, config.mqtt_port, keepalive=30)
        client.loop_start()
        if not connected.wait(config.timeout):
            raise TimeoutError("Conexão MQTT sem confirmação.")
        if errors:
            raise RuntimeError(errors[0])
        for index, (topic, payload) in enumerate(messages):
            info = client.publish(topic, payload, qos=1, retain=False)
            info.wait_for_publish(timeout=config.timeout)
            if not info.is_published():
                raise TimeoutError("Publicação MQTT sem confirmação PUBACK.")
            if interval and index < len(messages) - 1:
                time.sleep(interval)
    finally:
        client.disconnect()
        client.loop_stop()


def publicar_leituras(config: Config, samples: list[dict], interval: float = 1) -> None:
    messages = []
    for data in samples:

        payload = {**data, "id_leitura": data.get("id_leitura", str(uuid4()))}
        messages.append((config.topic_for(data["id_maquina"]),
                         json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")))
    publicar_payloads(config, messages, interval)
