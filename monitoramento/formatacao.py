from __future__ import annotations

from datetime import datetime


def numero(value: float | int) -> str:
    return f"{value:g}".replace(".", ",")


def mensagem(event: dict) -> str:
    data = event["dados"]
    received = event.get("recebido_em", "")
    if received:
        received = datetime.fromisoformat(received).astimezone().strftime("%d/%m/%Y %H:%M:%S %z")
    lines = [f"Máquina: {event['id_maquina']}", f"Situação: {event['situacao']}"]
    if received:
        lines.append(f"Recebido em: {received}")
    lines.append("Problemas identificados:")
    if not event["problemas"]:
        lines.append("- Nenhum.")
    for p in event["problemas"]:
        suffix = " °C" if p["codigo"] == "temperatura" else ""
        lines.append(f"- {p['descricao']}: {numero(p['valor'])}{suffix} "
                     f"({p['operador']} {numero(p['limite'])}{suffix}).")
    lines.extend([
        f"Produção: {numero(data['taxa_producao'])}/{numero(data['taxa_producao_esperada'])} "
        f"({numero(event['percentual_producao'])}% da esperada).",
        f"Tensão: {numero(data['tensao'])} V | Corrente: {numero(data['corrente'])} A",
        f"RECOMENDAÇÃO: {event['recomendacao']}",
    ])
    if event.get("id_evento"):
        lines.append(f"Evento: {event['id_evento']}")
    return "\n".join(lines)
