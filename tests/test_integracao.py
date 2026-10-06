import asyncio
import json
from dataclasses import replace
from email import policy
from email.parser import BytesParser
from uuid import uuid4

import pytest

from monitoramento.agente import monitorar
from monitoramento.broker import broker_local, porta_livre
from monitoramento.cenarios import CENARIOS
from monitoramento.cliente_mcp import conectar
from monitoramento.demo import demonstrar
from monitoramento.historico import Historico
from monitoramento.mqtt import publicar_payloads
from servicos_locais import servicos_locais

pytestmark = pytest.mark.integracao


def test_broker_autenticado_recebe_tres_cenarios_por_mqtt_e_mcp(config):
    config = replace(config, mqtt_port=porta_livre(), mqtt_username="operador", mqtt_password="senha-local-ç")

    async def run():
        async with broker_local(config.mqtt_port, username=config.mqtt_username, password=config.mqtt_password):
            ready = asyncio.Event()
            task = asyncio.create_task(monitorar(config, 3, ready=ready, idle_timeout=10))
            try:
                await asyncio.wait_for(ready.wait(), 15)
                topic = config.topic_for("MOTOR_01")
                payloads = [(topic, json.dumps(data).encode()) for data in CENARIOS.values()]
                await asyncio.to_thread(publicar_payloads, config, payloads)
                return await asyncio.wait_for(task, 20)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    results = asyncio.run(run())
    assert [result["situacao"] for result in results] == ["NORMAL", "ALERTA", "ALERTA"]
    assert len(config.outbox_path.read_text(encoding="utf-8").splitlines()) == 3


@pytest.mark.parametrize("username,password", [("", ""), ("intruso", "senha-local"), ("operador", "senha-errada")])
def test_broker_recusa_acesso_anonimo_e_credenciais_incorretas(config, username, password):
    config = replace(config, mqtt_port=porta_livre(), mqtt_username=username, mqtt_password=password, timeout=3)

    async def run():
        async with broker_local(config.mqtt_port, username="operador", password="senha-local"):
            with pytest.raises(RuntimeError, match="Broker MQTT.*simulador") as error:
                await asyncio.to_thread(publicar_payloads, config, [(config.topic_for("MOTOR_01"), b"{}")])
            assert "senha-local" not in str(error.value)
            assert "senha-errada" not in str(error.value)

    asyncio.run(run())


@pytest.mark.parametrize("username,password", [("operador", ""), ("", "senha-local")])
def test_credenciais_mqtt_incompletas_sao_rejeitadas(config, username, password):
    with pytest.raises(ValueError, match="MQTT_USERNAME e MQTT_PASSWORD"):
        replace(config, mqtt_username=username, mqtt_password=password).validate()


def test_demo_mqtt_mcp_reais_e_tres_mensagens_simuladas(config, tmp_path):

    report = asyncio.run(demonstrar(replace(config, mode="real"), tmp_path / "demo"))
    assert report["todos_passaram"]
    assert report["modo"] == "simulado"
    entries = (tmp_path / "demo/notificacoes_simuladas.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(entries) == 3
    assert len(Historico(tmp_path / "demo/historico.sqlite3").listar()) == 3


def real_config(config, local):
    return replace(config, mode="real", telegram_api_base=local["api_base"], telegram_token="token-teste",
                   telegram_chat_id="123", smtp_host="127.0.0.1", smtp_port=local["smtp_port"],
                   smtp_security="none", email_from="motor@example.test", email_to="operador@example.test")


def test_adaptadores_http_smtp_com_servidores_locais_e_mcp(config, tmp_path):
    with servicos_locais() as local:
        report = asyncio.run(demonstrar(real_config(config, local), tmp_path / "adaptadores", real=True))
        assert report["todos_passaram"]
        assert len(local["requests"]) == 2
        assert all(r["path"] == "/bottoken-teste/sendMessage" for r in local["requests"])
        assert "Temperatura elevada" in local["requests"][0]["body"]["text"]
        assert "Fator de potência baixo" in local["requests"][1]["body"]["text"]
        assert len(local["emails"]) == 1
        email = BytesParser(policy=policy.default).parsebytes(local["emails"][0])
        assert email["To"] == "operador@example.test"
        assert "[ALERTA] MOTOR_01" in email["Subject"]
        assert "Produção abaixo do esperado" in email.get_content()


def test_falha_telegram_nao_impede_email(config, tmp_path):
    with servicos_locais(http_status=500) as local:
        folder = tmp_path / "falha"
        with pytest.raises(RuntimeError, match="falhas"):
            asyncio.run(demonstrar(real_config(config, local), folder, real=True))
        report = json.loads((folder / "resultado.json").read_text(encoding="utf-8"))
        final = report["testes"][-1]["resultado"]["notificacoes"]
        assert [(n["canal"], n["status"]) for n in final] == [("telegram", "FALHA"), ("email", "ACEITO_PELO_SERVICO")]
        assert len(local["emails"]) == 1


def test_mensagem_invalida_nao_interrompe_e_uuid_e_deduplicado(config):
    config = replace(config, mqtt_port=porta_livre())
    reading_id = str(uuid4())
    alert = {**CENARIOS["temperatura_vibracao"], "id_leitura": reading_id}

    async def run():
        async with broker_local(config.mqtt_port):
            ready = asyncio.Event()
            task = asyncio.create_task(monitorar(config, 4, ready=ready, idle_timeout=10))
            try:
                await asyncio.wait_for(ready.wait(), 15)
                topic = config.topic_for("MOTOR_01")
                payloads = [(topic, b"{json-invalido}"), (topic, json.dumps(CENARIOS["normal"]).encode()),
                            (topic, json.dumps(alert).encode()), (topic, json.dumps(alert).encode())]
                await asyncio.to_thread(publicar_payloads, config, payloads)
                return await asyncio.wait_for(task, 20)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    results = asyncio.run(run())
    assert "erro" in results[0]
    assert results[1]["situacao"] == "NORMAL"
    assert results[2]["situacao"] == results[3]["situacao"] == "ALERTA"
    assert results[3]["notificacoes"][0]["reutilizado"] is True
    assert len(config.outbox_path.read_text(encoding="utf-8").splitlines()) == 1
    assert len(Historico(config.db_path).listar()) == 2


def test_descoberta_configuracao_e_erros_pelo_protocolo_mcp(config):
    async def run():
        async with conectar(config) as client:
            assert {"analisar_maquina", "enviar_alerta_telegram", "enviar_alerta_email"}.issubset(client.tools)
            settings = await client.chamar("verificar_configuracao", {})
            assert "TELEGRAM_BOT_TOKEN" in settings["telegram_pendente"]
            with pytest.raises(RuntimeError, match="Campos ausentes"):
                await client.chamar("analisar_maquina", {"dados": {"id_maquina": "MOTOR_01"}})
    asyncio.run(run())
