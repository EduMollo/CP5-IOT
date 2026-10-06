from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .agente import monitorar
from .broker import broker_local, porta_livre
from .cenarios import CENARIOS, ESPERADOS
from .config import Config, PROJECT_ROOT
from .mqtt import publicar_leituras


async def demonstrar(config: Config, directory: Path | None = None, real: bool = False) -> dict:
    if directory is None:
        label = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
        directory = PROJECT_ROOT / "resultados" / f"demonstracao-{label}"
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    config = replace(config, mqtt_host="127.0.0.1", mqtt_port=porta_livre(), mqtt_username="", mqtt_password="",
                     mqtt_tls=False, mqtt_prefix="industria/maquinas", cooldown=0,
                     mode="real" if real else "simulado", db_path=directory / "historico.sqlite3",
                     outbox_path=directory / "notificacoes_simuladas.jsonl")
    if real:
        pending = config.missing("telegram") + config.missing("email")
        if pending:
            raise ValueError("Demonstração real pendente: " + ", ".join(pending))
    ready = asyncio.Event()
    monitor_task = None
    async with broker_local(config.mqtt_port):
        monitor_task = asyncio.create_task(monitorar(config, max_messages=3, ready=ready, idle_timeout=20))
        try:

            ready_task = asyncio.create_task(ready.wait())
            try:
                done, _ = await asyncio.wait({monitor_task, ready_task}, timeout=25,
                                            return_when=asyncio.FIRST_COMPLETED)
                if monitor_task in done:
                    await monitor_task
                    raise RuntimeError("O monitor encerrou antes de confirmar a assinatura.")
                if ready_task not in done:
                    raise TimeoutError("O monitor não ficou pronto para a demonstração.")
            finally:
                ready_task.cancel()
                await asyncio.gather(ready_task, return_exceptions=True)
            await asyncio.to_thread(publicar_leituras, config, list(CENARIOS.values()), 0.1)
            results = await asyncio.wait_for(monitor_task, timeout=60)
        finally:
            if not monitor_task.done():
                monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
    expected_status = "ACEITO_PELO_SERVICO" if real else "SIMULADO"
    tests = []
    for name, result in zip(CENARIOS, results, strict=True):
        expected = ESPERADOS[name]
        actual = {"situacao": result.get("situacao"),
                  "problemas": [p["codigo"] for p in result.get("problemas", [])],
                  "canais": [n["canal"] for n in result.get("notificacoes", [])]}
        status_ok = all(n["status"] == expected_status for n in result.get("notificacoes", []))
        tests.append({"cenario": name, "esperado": expected, "obtido": actual,
                      "passou": actual == expected and status_ok, "resultado": result})
    report = {
        "executado_em": datetime.now().astimezone().isoformat(), "modo": config.mode,
        "infraestrutura": {"broker": "aMQTT local real", "protocolo_mqtt": "3.1.1", "qos": 1,
                           "mcp": "SDK oficial, servidor em processo separado via stdio"},
        "todos_passaram": all(t["passou"] for t in tests), "testes": tests,
        "diretorio": str(directory),
        "observacao": "Envios externos realizados; verificar os destinos." if real else
                      "MQTT e MCP reais; Telegram e e-mail simulados, sem envios externos.",
    }
    (directory / "resultado.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    lines = ["# Resultado da demonstração", "", f"Executado em: {report['executado_em']}", "",
             f"Modo: **{config.mode}**. {report['observacao']}", "",
             "| Cenário | Situação | Problemas | Notificações | Teste |", "|---|---|---|---|---|"]
    for test in tests:
        result = test["resultado"]
        notifications = "; ".join(f"{n['canal']}: {n['status']}" for n in result.get("notificacoes", [])) or "Nenhuma"
        descriptions = "; ".join(p["descricao"] for p in result.get("problemas", [])) or "Nenhum"
        lines.append(f"| {test['cenario']} | {result.get('situacao', 'ERRO')} | {descriptions} | {notifications} | "
                     f"{'PASSOU' if test['passou'] else 'FALHOU'} |")
    lines.extend(["", "O broker MQTT real foi iniciado localmente. O receptor assinou o tópico antes das publicações.",
                  "Cada análise e notificação foi solicitada pelo cliente ao servidor MCP em outro processo.",
                  "", "As mensagens completas e o histórico acompanham este relatório."])
    (directory / "resultado.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nRelatório: {directory / 'resultado.md'}", flush=True)
    if not report["todos_passaram"]:
        raise RuntimeError("A demonstração encontrou falhas. Consulte o relatório gerado.")
    return report
