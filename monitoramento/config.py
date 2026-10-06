from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_prefix: str = "industria/maquinas"
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_tls: bool = False
    timeout: float = 10.0
    mode: str = "simulado"
    cooldown: float = 300.0
    db_path: Path = PROJECT_ROOT / "data/historico.sqlite3"
    outbox_path: Path = PROJECT_ROOT / "data/notificacoes_simuladas.jsonl"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""

    @classmethod
    def load(cls) -> Config:
        load_dotenv(PROJECT_ROOT / ".env", override=False)

        def path(name: str, default: str) -> Path:
            value = Path(os.getenv(name, default)).expanduser()
            return value if value.is_absolute() else PROJECT_ROOT / value

        def boolean(name: str, default: str = "false") -> bool:
            value = os.getenv(name, default).lower().strip()
            if value not in {"true", "false", "1", "0"}:
                raise ValueError(f"{name}: use true ou false.")
            return value in {"true", "1"}

        config = cls(
            mqtt_host=os.getenv("MQTT_HOST", "127.0.0.1"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            mqtt_prefix=os.getenv("MQTT_PREFIX", "industria/maquinas").strip("/"),
            mqtt_username=os.getenv("MQTT_USERNAME", ""),
            mqtt_password=os.getenv("MQTT_PASSWORD", ""),
            mqtt_tls=boolean("MQTT_TLS"),
            timeout=float(os.getenv("NETWORK_TIMEOUT", "10")),
            mode=os.getenv("NOTIFICATION_MODE", "simulado").strip().lower(),
            cooldown=float(os.getenv("ALERT_COOLDOWN_SECONDS", "300")),
            db_path=path("MACHINE_DB_PATH", "data/historico.sqlite3"),
            outbox_path=path("OUTBOX_PATH", "data/notificacoes_simuladas.jsonl"),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            telegram_api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_security=os.getenv("SMTP_SECURITY", "starttls").lower(),
            smtp_user=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            email_from=os.getenv("EMAIL_FROM", ""),
            email_to=os.getenv("EMAIL_TO", ""),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode not in {"simulado", "real"}:
            raise ValueError("NOTIFICATION_MODE deve ser simulado ou real.")
        if bool(self.mqtt_username) != bool(self.mqtt_password):
            raise ValueError("Preencha MQTT_USERNAME e MQTT_PASSWORD juntos, ou deixe ambos vazios.")
        if not (1 <= self.mqtt_port <= 65535 and 1 <= self.smtp_port <= 65535):
            raise ValueError("As portas devem estar entre 1 e 65535.")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("NETWORK_TIMEOUT deve ser positivo e finito.")
        if not math.isfinite(self.cooldown) or self.cooldown < 0:
            raise ValueError("ALERT_COOLDOWN_SECONDS deve ser não negativo e finito.")
        if not self.mqtt_prefix or any(c in self.mqtt_prefix for c in "+#\x00"):
            raise ValueError("MQTT_PREFIX deve ser um prefixo sem curingas.")
        if self.smtp_security not in {"starttls", "ssl", "none"}:
            raise ValueError("SMTP_SECURITY deve ser starttls, ssl ou none.")
        parsed = urlparse(self.telegram_api_base)
        official = self.telegram_api_base == "https://api.telegram.org"
        local_test = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if not (official or local_test):
            raise ValueError("TELEGRAM_API_BASE: use a API oficial ou um servidor de teste local.")

    @property
    def mqtt_topic(self) -> str:
        return f"{self.mqtt_prefix}/+/sensores"

    def topic_for(self, machine: str) -> str:
        return f"{self.mqtt_prefix}/{machine}/sensores"

    def missing(self, channel: str) -> list[str]:
        if channel == "telegram":
            fields = {"TELEGRAM_BOT_TOKEN": self.telegram_token, "TELEGRAM_CHAT_ID": self.telegram_chat_id}
        else:
            fields = {"SMTP_HOST": self.smtp_host, "EMAIL_FROM": self.email_from, "EMAIL_TO": self.email_to}
            if self.smtp_user or self.smtp_password:
                fields.update(SMTP_USERNAME=self.smtp_user, SMTP_PASSWORD=self.smtp_password)
        return [name for name, value in fields.items() if not value.strip()]

    def mcp_environment(self) -> dict[str, str]:
        values = {
            "MQTT_HOST": self.mqtt_host, "MQTT_PORT": self.mqtt_port, "MQTT_PREFIX": self.mqtt_prefix,
            "MQTT_USERNAME": self.mqtt_username, "MQTT_PASSWORD": self.mqtt_password,
            "MQTT_TLS": "true" if self.mqtt_tls else "false",
            "NOTIFICATION_MODE": self.mode, "ALERT_COOLDOWN_SECONDS": self.cooldown,
            "MACHINE_DB_PATH": self.db_path, "OUTBOX_PATH": self.outbox_path,
            "NETWORK_TIMEOUT": self.timeout, "TELEGRAM_BOT_TOKEN": self.telegram_token,
            "TELEGRAM_CHAT_ID": self.telegram_chat_id, "TELEGRAM_API_BASE": self.telegram_api_base,
            "SMTP_HOST": self.smtp_host, "SMTP_PORT": self.smtp_port,
            "SMTP_SECURITY": self.smtp_security, "SMTP_USERNAME": self.smtp_user,
            "SMTP_PASSWORD": self.smtp_password, "EMAIL_FROM": self.email_from, "EMAIL_TO": self.email_to,
            "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1",
        }
        return {key: str(value) for key, value in values.items()}
