import math

import pytest

from monitoramento.cenarios import BASE, CENARIOS, ESPERADOS
from monitoramento.regras import DadosInvalidos, analisar


@pytest.mark.parametrize("name", CENARIOS)
def test_tres_cenarios_obrigatorios(name):
    result = analisar(CENARIOS[name])
    expected = ESPERADOS[name]
    assert result["situacao"] == expected["situacao"]
    assert [p["codigo"] for p in result["problemas"]] == expected["problemas"]
    assert result["canais"] == expected["canais"]
    assert result["recomendacao"]


@pytest.mark.parametrize("field,value,codes,channels", [
    ("temperatura", 80, [], []), ("temperatura", 80.001, ["temperatura"], ["telegram"]),
    ("vibracao", 7, [], []), ("vibracao", 7.001, ["vibracao"], ["telegram"]),
    ("fator_potencia", 0.70, [], []), ("fator_potencia", 0.6999, ["fator_potencia"], ["telegram", "email"]),
    ("taxa_producao", 48, [], []), ("taxa_producao", 47.999, ["producao"], ["telegram", "email"]),
])
def test_limites_estritos_e_condicoes_isoladas(field, value, codes, channels):
    result = analisar({**BASE, field: value})
    assert [p["codigo"] for p in result["problemas"]] == codes
    assert result["canais"] == channels


def test_todos_limites_exatos_e_normal():
    result = analisar({**BASE, "temperatura": 80, "vibracao": 7, "fator_potencia": 0.70, "taxa_producao": 48})
    assert result["situacao"] == "NORMAL"
    assert result["percentual_producao"] == 80


def test_producao_decimal_no_limite_nao_dispara_por_arredondamento_binario():
    result = analisar({**BASE, "taxa_producao": 0.56, "taxa_producao_esperada": 0.7})
    assert result["situacao"] == "NORMAL"
    assert result["percentual_producao"] == 80


def test_quatro_problemas_e_dois_canais():
    result = analisar({**BASE, "temperatura": 86.5, "vibracao": 8.2, "fator_potencia": 0.62, "taxa_producao": 42})
    assert len(result["problemas"]) == 4
    assert result["percentual_producao"] == 70
    assert result["canais"] == ["telegram", "email"]


@pytest.mark.parametrize("field", BASE)
def test_campo_obrigatorio_ausente(field):
    data = dict(BASE)
    del data[field]
    with pytest.raises(DadosInvalidos, match="Campos ausentes"):
        analisar(data)


@pytest.mark.parametrize("field,value", [
    ("temperatura", "85"), ("temperatura", True), ("temperatura", math.nan),
    ("corrente", math.inf), ("taxa_producao_esperada", 0),
    ("vibracao", -1), ("fator_potencia", 1.1), ("id_maquina", ""),
    ("id_maquina", "MOTOR/01"), ("temperatura", 10 ** 400),
])
def test_valores_invalidos(field, value):
    with pytest.raises(DadosInvalidos):
        analisar({**BASE, field: value})


def test_mensagem_deve_ser_objeto():
    with pytest.raises(DadosInvalidos):
        analisar([BASE])


def test_tensao_e_corrente_nao_adicionam_regras():
    assert analisar({**BASE, "tensao": 500, "corrente": 200})["situacao"] == "NORMAL"
