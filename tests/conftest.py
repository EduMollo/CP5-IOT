from dataclasses import replace

import pytest

from monitoramento.config import Config
from monitoramento.historico import Historico


@pytest.fixture
def config(tmp_path):
    return replace(Config(), cooldown=0, db_path=tmp_path / "historico.sqlite3",
                   outbox_path=tmp_path / "outbox.jsonl")


@pytest.fixture
def history(config):
    return Historico(config.db_path)
