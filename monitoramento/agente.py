from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from uuid import UUID, uuid4

from .cliente_mcp import ClienteMCP, conectar
from .config import Config
from .formatacao import mensagem
from .mqtt import ReceptorMQTT

logger = logging.getLogger(__name__)


def rejeitar_constante(value: str):
    raise ValueError(f"Constante JSON inválida: {value}")


async def processar(client: ClienteMCP, config: Config, topic: str, payload: bytes) -> dict:
    try:
        data = json.loads(payload.decode("utf-8"), parse_constant=rejeitar_constante)
        if not isinstance(data, dict):
            raise ValueError("A mensagem deve ser um objeto JSON.")
        if topic != config.topic_for(data.get("id_maquina", "")):
            raise ValueError("O id_maquina não corresponde ao tópico MQTT.")
        event_id = str(UUID(data["id_leitura"])) if "id_leitura" in data else str(uuid4())
        event = await client.chamar("analisar_maquina", {"dados": data, "id_evento": event_id})
    except Exception as error:
        logger.error("Leitura rejeitada no tópico %s: %s", topic, error)
        return {"erro": str(error), "topico": topic}

    notifications = []
    for channel in event["canais"]:
        try:
            result = await client.chamar(f"enviar_alerta_{channel}", {"id_evento": event["id_evento"]})
        except Exception:

            result = {"id_evento": event["id_evento"], "canal": channel, "modo": config.mode,
                      "status": "ERRO_MCP", "detalhe": "Não foi possível obter o resultado da ferramenta de envio."}
            logger.exception("Falha MCP ao acionar o canal %s.", channel)
        notifications.append(result)
    output = {**event, "notificacoes": notifications}
    print("\n" + mensagem(event), flush=True)
    if not notifications:
        print("Notificações: nenhuma exigida.", flush=True)
    for result in notifications:
        reused = " (resultado anterior; envio não repetido)" if result.get("reutilizado") else ""
        print(f"Notificação {result['canal']}: {result['status']}{reused}. {result.get('detalhe', '')}", flush=True)
    return output


async def monitorar(config: Config, max_messages: int | None = None, ready: asyncio.Event | None = None,
                    on_result: Callable[[dict], None] | None = None, idle_timeout: float | None = None) -> list[dict]:
    results = []
    async with conectar(config) as client:
        print("Servidor MCP conectado. Ferramentas: " + ", ".join(client.tools), flush=True)
        async with ReceptorMQTT(config) as source:
            print(f"Assinatura MQTT confirmada: {config.mqtt_host}:{config.mqtt_port}/{config.mqtt_topic}", flush=True)
            if ready:
                ready.set()
            count = 0
            while max_messages is None or count < max_messages:
                if idle_timeout is None:
                    topic, payload = await source.queue.get()
                else:
                    topic, payload = await asyncio.wait_for(source.queue.get(), timeout=idle_timeout)
                result = await processar(client, config, topic, payload)
                count += 1
                if max_messages is not None:
                    results.append(result)
                if on_result:
                    on_result(result)
                source.queue.task_done()
    return results
