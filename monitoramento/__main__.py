from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .agente import monitorar
from .broker import executar_broker
from .cenarios import CENARIOS
from .cliente_mcp import conectar
from .config import Config, PROJECT_ROOT
from .demo import demonstrar
from .mqtt import publicar_leituras


async def comando_mcp(config: Config, args) -> None:
    async with conectar(config) as client:
        if args.command == "verificar":
            output = await client.chamar("verificar_configuracao", {})
            output["ferramentas_mcp"] = client.tools
        elif args.command == "historico":
            output = await client.chamar("consultar_historico", {"limite": args.limite, "id_maquina": args.maquina})
        else:
            events = await client.chamar("consultar_historico", {"id_evento": args.id_evento})
            if not events["eventos"]:
                raise ValueError("Evento não encontrado na base configurada.")
            event = events["eventos"][0]
            output = {"id_evento": event["id_evento"], "notificacoes": []}
            for channel in event["canais"]:
                output["notificacoes"].append(await client.chamar(f"enviar_alerta_{channel}", {"id_evento": event["id_evento"]}))
        print(json.dumps(output, ensure_ascii=False, indent=2))


def detalhe(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(detalhe(item) for item in error.exceptions)
    return str(error) or type(error).__name__


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    logging.getLogger("amqtt").setLevel(logging.ERROR)
    parser = argparse.ArgumentParser(description="Monitoramento industrial com MQTT e MCP.")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Executa os três testes com broker local e MCP reais.")
    demo.add_argument("--real", action="store_true", help="Envia aos destinos configurados em vez de simular.")
    broker = sub.add_parser("broker", help="Inicia um broker MQTT apenas em 127.0.0.1.")
    broker.add_argument("--porta", type=int)
    monitor = sub.add_parser("monitorar", help="Recebe leituras no broker configurado.")
    monitor.add_argument("--max-mensagens", type=int)
    simulator = sub.add_parser("simular", help="Publica mensagens JSON no broker configurado.")
    simulator.add_argument("--cenario", choices=[*CENARIOS, "todos"], default="todos")
    simulator.add_argument("--arquivo", help="Arquivo JSON com uma leitura ou lista de leituras.")
    simulator.add_argument("--intervalo", type=float, default=1)
    sub.add_parser("verificar", help="Verifica as ferramentas MCP e as configurações sem expor segredos.")
    history = sub.add_parser("historico", help="Consulta leituras e envios pela ferramenta MCP.")
    history.add_argument("--limite", type=int, default=10)
    history.add_argument("--maquina")
    notify = sub.add_parser("notificar", help="Tenta os envios pendentes de um evento existente.")
    notify.add_argument("id_evento")
    args = parser.parse_args()
    try:
        config = Config.load()
        (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
        handler = logging.FileHandler(PROJECT_ROOT / "logs/monitoramento.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(handler)
        if args.command == "demo":
            asyncio.run(demonstrar(config, real=args.real))
        elif args.command == "broker":
            port = args.porta or config.mqtt_port
            if not 1 <= port <= 65535:
                raise ValueError("Porta inválida.")
            if config.mqtt_tls:
                raise ValueError("O broker local usa MQTT_TLS=false. Para TLS, use um broker externo configurado.")
            asyncio.run(executar_broker(port, username=config.mqtt_username, password=config.mqtt_password))
        elif args.command == "monitorar":
            if args.max_mensagens is not None and args.max_mensagens < 1:
                raise ValueError("--max-mensagens deve ser positivo.")
            asyncio.run(monitorar(config, args.max_mensagens))
        elif args.command == "simular":
            if args.intervalo < 0:
                raise ValueError("--intervalo não pode ser negativo.")
            if args.arquivo:
                with open(args.arquivo, encoding="utf-8") as file:
                    samples = json.load(file)
                samples = samples if isinstance(samples, list) else [samples]
            else:
                samples = list(CENARIOS.values()) if args.cenario == "todos" else [CENARIOS[args.cenario]]
            publicar_leituras(config, samples, args.intervalo)
            print(f"{len(samples)} mensagem(ns) publicada(s) com confirmação MQTT.")
        else:
            asyncio.run(comando_mcp(config, args))
        return 0
    except KeyboardInterrupt:
        print("\nExecução encerrada.")
        return 0
    except Exception as error:
        print("ERRO: " + detalhe(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
