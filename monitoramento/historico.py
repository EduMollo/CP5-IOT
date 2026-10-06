from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


class Historico:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS eventos (
                    id_evento TEXT PRIMARY KEY, id_maquina TEXT NOT NULL,
                    recebido_em TEXT NOT NULL, analise TEXT NOT NULL, assinatura TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notificacoes (
                    id_evento TEXT NOT NULL REFERENCES eventos(id_evento),
                    canal TEXT NOT NULL, modo TEXT NOT NULL, status TEXT NOT NULL,
                    atualizado_em TEXT NOT NULL, resultado TEXT NOT NULL,
                    PRIMARY KEY (id_evento, canal, modo)
                );
                CREATE INDEX IF NOT EXISTS eventos_maquina ON eventos(id_maquina, recebido_em);
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def salvar(self, analysis: dict, event_id: str | None = None) -> dict:
        event_id = str(UUID(event_id)) if event_id else str(uuid4())
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT analise FROM eventos WHERE id_evento=?", (event_id,)).fetchone()
            if row:
                stored = json.loads(row[0])
                if stored["dados"] != analysis["dados"]:
                    raise ValueError("O id_evento já pertence a outra leitura.")
                return stored
            event = {**analysis, "id_evento": event_id, "recebido_em": agora()}
            signature = ",".join(p["codigo"] for p in analysis["problemas"])
            conn.execute("INSERT INTO eventos VALUES (?,?,?,?,?)", (
                event_id, analysis["id_maquina"], event["recebido_em"],
                json.dumps(event, ensure_ascii=False, allow_nan=False), signature,
            ))
        return event

    def obter(self, event_id: str) -> dict:
        with self.connection() as conn:
            row = conn.execute("SELECT analise FROM eventos WHERE id_evento=?", (event_id,)).fetchone()
        if not row:
            raise ValueError("Evento não encontrado no histórico.")
        return json.loads(row[0])

    def listar(self, limit: int = 10, machine: str | None = None, event_id: str | None = None) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("limite deve estar entre 1 e 100.")
        where, params = [], []
        if machine:
            where.append("id_maquina=?")
            params.append(machine)
        if event_id:
            where.append("id_evento=?")
            params.append(event_id)
        query = "SELECT analise FROM eventos"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY recebido_em DESC LIMIT ?"
        with self.connection() as conn:
            events = [json.loads(row[0]) for row in conn.execute(query, (*params, limit))]
            for event in events:
                rows = conn.execute("SELECT resultado FROM notificacoes WHERE id_evento=? ORDER BY canal,modo",
                                    (event["id_evento"],))
                event["notificacoes"] = [json.loads(row[0]) for row in rows]
        return events

    def reservar_envio(self, event: dict, channel: str, mode: str, cooldown: float) -> dict | None:
        event_id = event["id_evento"]
        now = agora()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT resultado,status FROM notificacoes WHERE id_evento=? AND canal=? AND modo=?",
                               (event_id, channel, mode)).fetchone()
            if row and row["status"] not in {"FALHA", "CONFIGURACAO_PENDENTE"}:
                return {**json.loads(row["resultado"]), "reutilizado": True}
            if cooldown > 0:
                last = conn.execute("""
                    SELECT n.atualizado_em,e.assinatura FROM notificacoes n
                    JOIN eventos e ON e.id_evento=n.id_evento
                    WHERE e.id_maquina=? AND n.canal=? AND n.modo=?
                    AND n.status IN ('SIMULADO','ACEITO_PELO_SERVICO')
                    ORDER BY n.atualizado_em DESC LIMIT 1
                """, (event["id_maquina"], channel, mode)).fetchone()
                signature = ",".join(p["codigo"] for p in event["problemas"])
                if last and last["assinatura"] == signature:
                    seconds = (datetime.fromisoformat(now) - datetime.fromisoformat(last["atualizado_em"])).total_seconds()
                    recovered = conn.execute("""
                        SELECT 1 FROM eventos WHERE id_maquina=? AND assinatura='' AND recebido_em>? LIMIT 1
                    """, (event["id_maquina"], last["atualizado_em"])).fetchone()
                    if seconds < cooldown and not recovered:
                        result = {"id_evento": event_id, "canal": channel, "modo": mode,
                                  "status": "SUPRIMIDO", "detalhe": "Alerta repetido dentro do intervalo configurado."}
                        self._write(conn, result, now)
                        return result
            self._write(conn, {"id_evento": event_id, "canal": channel, "modo": mode,
                               "status": "EM_ENVIO", "detalhe": "Envio reservado."}, now)
        return None

    @staticmethod
    def _write(conn, result: dict, timestamp: str):
        conn.execute("""
            INSERT INTO notificacoes VALUES (?,?,?,?,?,?)
            ON CONFLICT(id_evento,canal,modo) DO UPDATE SET
            status=excluded.status,atualizado_em=excluded.atualizado_em,resultado=excluded.resultado
        """, (result["id_evento"], result["canal"], result["modo"], result["status"], timestamp,
              json.dumps(result, ensure_ascii=False, allow_nan=False)))

    def registrar_envio(self, result: dict) -> None:
        with self.connection() as conn:
            self._write(conn, result, agora())
