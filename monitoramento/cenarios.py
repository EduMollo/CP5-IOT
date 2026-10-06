BASE = {
    "id_maquina": "MOTOR_01", "temperatura": 65, "vibracao": 3,
    "tensao": 220, "corrente": 18.5, "fator_potencia": 0.92,
    "taxa_producao": 58, "taxa_producao_esperada": 60,
}

CENARIOS = {
    "normal": dict(BASE),
    "temperatura_vibracao": {**BASE, "temperatura": 86.5, "vibracao": 8.2, "taxa_producao": 60},
    "producao_fator": {**BASE, "temperatura": 70, "vibracao": 4, "fator_potencia": 0.62, "taxa_producao": 42},
}

ESPERADOS = {
    "normal": {"situacao": "NORMAL", "problemas": [], "canais": []},
    "temperatura_vibracao": {"situacao": "ALERTA", "problemas": ["temperatura", "vibracao"], "canais": ["telegram"]},
    "producao_fator": {"situacao": "ALERTA", "problemas": ["fator_potencia", "producao"], "canais": ["telegram", "email"]},
}
