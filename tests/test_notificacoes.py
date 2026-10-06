import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from monitoramento.cenarios import BASE, CENARIOS
from monitoramento.notificacoes import Notificador
from monitoramento.regras import analisar


def event(history, name="producao_fator"):
    return history.salvar(analisar(CENARIOS[name]))


def test_mensagem_por_canal_e_idempotencia(config, history):
    data = event(history)
    notifier = Notificador(config, history)
    first = asyncio.run(notifier.enviar(data["id_evento"], "telegram"))
    second = asyncio.run(notifier.enviar(data["id_evento"], "telegram"))
    email = asyncio.run(notifier.enviar(data["id_evento"], "email"))
    assert first["status"] == email["status"] == "SIMULADO"
    assert second["reutilizado"] is True
    entries = [json.loads(line) for line in config.outbox_path.read_text(encoding="utf-8").splitlines()]
    assert [n["canal"] for n in entries] == ["telegram", "email"]
    assert "Fator de potência baixo" in entries[0]["mensagem"]
    assert "Produção abaixo do esperado" in entries[0]["mensagem"]


@pytest.mark.parametrize("name,channel", [("normal", "telegram"), ("normal", "email"), ("temperatura_vibracao", "email")])
def test_canais_nao_exigidos_nao_enviam(config, history, name, channel):
    data = event(history, name)
    result = asyncio.run(Notificador(config, history).enviar(data["id_evento"], channel))
    assert result["status"] == "NAO_APLICAVEL"
    assert not config.outbox_path.exists()


def test_intervalo_novo_problema_e_recuperacao(config, history):
    notifier = Notificador(replace(config, cooldown=300), history)
    first = event(history, "temperatura_vibracao")
    repeat = event(history, "temperatura_vibracao")
    changed = event(history)
    assert asyncio.run(notifier.enviar(first["id_evento"], "telegram"))["status"] == "SIMULADO"
    assert asyncio.run(notifier.enviar(repeat["id_evento"], "telegram"))["status"] == "SUPRIMIDO"
    assert asyncio.run(notifier.enviar(changed["id_evento"], "telegram"))["status"] == "SIMULADO"
    history.salvar(analisar(BASE))
    recurring = event(history)
    assert asyncio.run(notifier.enviar(recurring["id_evento"], "telegram"))["status"] == "SIMULADO"


def test_maquinas_independentes(config, history):
    notifier = Notificador(replace(config, cooldown=300), history)
    first = event(history)
    other = history.salvar(analisar({**CENARIOS["producao_fator"], "id_maquina": "MOTOR_02"}))
    for data in (first, other):
        assert asyncio.run(notifier.enviar(data["id_evento"], "telegram"))["status"] == "SIMULADO"


def test_mesmo_uuid_nao_pode_trocar_leitura(history):
    first = event(history)
    assert history.salvar(analisar(CENARIOS["producao_fator"]), first["id_evento"]) == first
    with pytest.raises(ValueError, match="outra leitura"):
        history.salvar(analisar(BASE), first["id_evento"])


def test_real_sem_credenciais_nao_finge_envio(config, history):
    data = event(history)
    notifier = Notificador(replace(config, mode="real"), history)
    for channel in ("telegram", "email"):
        result = asyncio.run(notifier.enviar(data["id_evento"], channel))
        assert result["status"] == "CONFIGURACAO_PENDENTE"
        assert result["campos_ausentes"]
    assert not config.outbox_path.exists()


def test_envio_simulado_nao_impede_envio_real(config, history):
    data = event(history)
    asyncio.run(Notificador(config, history).enviar(data["id_evento"], "telegram"))
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})

    real = replace(config, mode="real", telegram_token="token-teste", telegram_chat_id="123")
    notifier = Notificador(real, history, httpx.MockTransport(handler))
    assert asyncio.run(notifier.enviar(data["id_evento"], "telegram"))["status"] == "ACEITO_PELO_SERVICO"
    assert len(calls) == 1
    records = history.listar()[0]["notificacoes"]
    assert {r["modo"] for r in records} == {"real", "simulado"}


def test_falha_pode_ser_tentada_novamente(config, history):
    data = event(history)
    real = replace(config, mode="real", telegram_token="token-teste", telegram_chat_id="123")
    responses = iter([httpx.Response(500, json={"ok": False}), httpx.Response(200, json={"ok": True, "result": {"message_id": 2}})])
    notifier = Notificador(real, history, httpx.MockTransport(lambda _: next(responses)))
    assert asyncio.run(notifier.enviar(data["id_evento"], "telegram"))["status"] == "FALHA"
    assert asyncio.run(notifier.enviar(data["id_evento"], "telegram"))["status"] == "ACEITO_PELO_SERVICO"


def test_timeout_incerto_nao_reenvia_e_nao_expoe_token(config, history):
    data = event(history)
    real = replace(config, mode="real", telegram_token="segredo-nao-expor", telegram_chat_id="123")
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout(f"Timeout em {request.url}")

    notifier = Notificador(real, history, httpx.MockTransport(handler))
    result = asyncio.run(notifier.enviar(data["id_evento"], "telegram"))
    repeated = asyncio.run(notifier.enviar(data["id_evento"], "telegram"))
    assert result["status"] == "INCERTO"
    assert repeated["reutilizado"] is True
    assert "segredo-nao-expor" not in json.dumps(result)
    assert len(calls) == 1
