from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

CAMPOS_NUMERICOS = (
    "temperatura", "vibracao", "tensao", "corrente", "fator_potencia",
    "taxa_producao", "taxa_producao_esperada",
)


class DadosInvalidos(ValueError):
    pass


def validar(dados: Any) -> dict:
    if not isinstance(dados, dict):
        raise DadosInvalidos("A mensagem deve ser um objeto JSON.")
    ausentes = [name for name in ("id_maquina", *CAMPOS_NUMERICOS) if name not in dados]
    if ausentes:
        raise DadosInvalidos("Campos ausentes: " + ", ".join(ausentes))
    machine = dados["id_maquina"]
    if not isinstance(machine, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", machine):
        raise DadosInvalidos("id_maquina: use 1 a 64 letras, números, _ ou -.")
    normalized = {"id_maquina": machine}
    for name in CAMPOS_NUMERICOS:
        value = dados[name]
        if type(value) not in (int, float):
            raise DadosInvalidos(f"{name} deve ser numérico (não texto ou booleano).")
        try:
            valid = math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid:
            raise DadosInvalidos(f"{name} deve ser finito.")
        if name != "temperatura" and value < 0:
            raise DadosInvalidos(f"{name} não pode ser negativo.")
        normalized[name] = value
    if not 0 <= normalized["fator_potencia"] <= 1:
        raise DadosInvalidos("fator_potencia deve estar entre 0 e 1.")
    if normalized["taxa_producao_esperada"] <= 0:
        raise DadosInvalidos("taxa_producao_esperada deve ser maior que zero.")
    return normalized


def analisar(dados: Any) -> dict:
    values = validar(dados)
    produced = Decimal(str(values["taxa_producao"]))
    expected = Decimal(str(values["taxa_producao_esperada"]))
    percentage = produced / expected * 100
    if not math.isfinite(float(percentage)):
        raise DadosInvalidos("A relação entre produção e produção esperada excede o intervalo suportado.")
    problems = []
    rules = [
        (values["temperatura"] > 80, "temperatura", "Temperatura elevada", values["temperatura"], 80, ">",
         "Inspecionar ventilação, refrigeração e condições de carga do motor."),
        (values["vibracao"] > 7, "vibracao", "Vibração elevada", values["vibracao"], 7, ">",
         "Verificar fixação, alinhamento e componentes mecânicos do motor."),
        (values["fator_potencia"] < 0.70, "fator_potencia", "Fator de potência baixo", values["fator_potencia"], 0.70, "<",
         "Verificar as condições elétricas e o comportamento da carga."),
        (produced < Decimal("0.8") * expected, "producao", "Produção abaixo do esperado",
         values["taxa_producao"], float(Decimal("0.8") * expected), "<",
         "Verificar interrupções, restrições do processo e condições operacionais."),
    ]
    for condition, code, description, value, limit, operator, recommendation in rules:
        if condition:
            problems.append({"codigo": code, "descricao": description, "valor": value,
                             "limite": limit, "operador": operator, "recomendacao": recommendation})
    channels = ["telegram"] if problems else []
    if any(p["codigo"] in {"fator_potencia", "producao"} for p in problems):
        channels.append("email")
    recommendation = "Manter o monitoramento periódico da máquina."
    if problems:
        recommendation = "Realizar inspeção do motor e verificar as condições de funcionamento. "
        recommendation += " ".join(p["recomendacao"] for p in problems)
    return {
        "id_maquina": values["id_maquina"], "situacao": "ALERTA" if problems else "NORMAL",
        "dados": values, "percentual_producao": float(round(percentage, 2)),
        "problemas": problems, "recomendacao": recommendation, "canais": channels,
    }
