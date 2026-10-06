from __future__ import annotations

import asyncio
import json
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

import httpx

from .config import Config
from .formatacao import mensagem
from .historico import Historico


class Notificador:
    def __init__(self, config: Config, history: Historico, transport: httpx.AsyncBaseTransport | None = None):
        self.config, self.history, self.transport = config, history, transport

    async def enviar(self, event_id: str, channel: str) -> dict:
        if channel not in {"telegram", "email"}:
            raise ValueError("Canal desconhecido.")
        event = self.history.obter(event_id)
        base = {"id_evento": event_id, "canal": channel, "modo": self.config.mode}
        if channel not in event["canais"]:
            return {**base, "status": "NAO_APLICAVEL", "detalhe": "Este evento não exige envio por este canal."}
        previous = self.history.reservar_envio(event, channel, self.config.mode, self.config.cooldown)
        if previous:
            return previous
        if self.config.mode == "simulado":
            try:
                self._simular(event, channel)
                result = {"status": "SIMULADO", "detalhe": "Mensagem salva localmente; nenhum envio externo."}
            except OSError:
                result = {"status": "FALHA", "detalhe": "Não foi possível gravar a mensagem simulada."}
        else:
            missing = self.config.missing(channel)
            if missing:
                result = {"status": "CONFIGURACAO_PENDENTE", "campos_ausentes": missing,
                          "detalhe": "Preencha as variáveis indicadas no arquivo .env."}
            elif channel == "telegram":
                result = await self._telegram(event)
            else:
                result = await asyncio.to_thread(self._email, event)
        result = {**base, **result}
        self.history.registrar_envio(result)
        return result

    def _simular(self, event: dict, channel: str) -> None:
        path = Path(self.config.outbox_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"id_evento": event["id_evento"], "canal": channel, "modo": "simulado",
                 "status": "SIMULADO", "assunto": self._subject(event), "mensagem": mensagem(event)}
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")

    @staticmethod
    def _subject(event: dict) -> str:
        return f"[ALERTA] {event['id_maquina']} - Monitoramento industrial"

    async def _telegram(self, event: dict) -> dict:
        url = f"{self.config.telegram_api_base}/bot{self.config.telegram_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout, transport=self.transport,
                                         follow_redirects=False) as client:
                response = await client.post(url, json={"chat_id": self.config.telegram_chat_id,
                                                       "text": mensagem(event)})
            body = response.json()
            if response.is_success and body.get("ok") is True:
                return {"status": "ACEITO_PELO_SERVICO", "detalhe": "Telegram aceitou a mensagem.",
                        "message_id": body.get("result", {}).get("message_id")}
            return {"status": "FALHA", "detalhe": f"Telegram recusou a solicitação (HTTP {response.status_code})."}
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return {"status": "FALHA", "detalhe": "Não foi possível conectar ao Telegram."}
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):

            return {"status": "INCERTO", "detalhe": "Sem confirmação do Telegram; confira o destino antes de reenviar."}

    def _email(self, event: dict) -> dict:
        for address in (self.config.email_from, self.config.email_to):
            parsed = parseaddr(address)[1]
            if any(c in address for c in "\r\n") or "@" not in parsed or "," in address or ";" in address:
                return {"status": "FALHA", "detalhe": "Configure um endereço válido em EMAIL_FROM e EMAIL_TO."}
        mail = EmailMessage()
        mail["Subject"] = self._subject(event)
        mail["From"] = self.config.email_from
        mail["To"] = self.config.email_to
        mail["Message-ID"] = f"<{event['id_evento']}@monitoramento.local>"
        mail.set_content(mensagem(event), charset="utf-8")
        sending = False
        accepted = False
        try:
            security = self.config.smtp_security
            kwargs = {"host": self.config.smtp_host, "port": self.config.smtp_port, "timeout": self.config.timeout}
            if security == "ssl":
                smtp = smtplib.SMTP_SSL(**kwargs, context=ssl.create_default_context())
            else:
                smtp = smtplib.SMTP(**kwargs)
            with smtp:
                if security == "starttls":
                    smtp.starttls(context=ssl.create_default_context())
                if self.config.smtp_user:
                    smtp.login(self.config.smtp_user, self.config.smtp_password)
                sending = True
                rejected = smtp.send_message(mail)
                if rejected:
                    return {"status": "FALHA", "detalhe": "O servidor SMTP recusou o destinatário."}
                accepted = True
            return {"status": "ACEITO_PELO_SERVICO", "detalhe": "Servidor SMTP aceitou o e-mail; confira a caixa de entrada."}
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
                smtplib.SMTPAuthenticationError, smtplib.SMTPDataError):
            return {"status": "FALHA", "detalhe": "SMTP recusou remetente, destinatário, autenticação ou conteúdo."}
        except (OSError, smtplib.SMTPException, socket.timeout):
            if accepted:
                return {"status": "ACEITO_PELO_SERVICO", "detalhe": "SMTP aceitou o e-mail, mas o encerramento da conexão falhou."}
            if sending:
                return {"status": "INCERTO", "detalhe": "Sem confirmação SMTP; confira o destino antes de reenviar."}
            return {"status": "FALHA", "detalhe": "Falha na conexão ou negociação com o servidor SMTP."}
