from uuid import uuid4

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):

    if config.getoption("basetemp") is not None:
        return
    project_root = config.rootpath.resolve()
    work_root = (project_root / "work").resolve()
    if not work_root.is_relative_to(project_root):
        raise pytest.UsageError("A pasta work deve permanecer dentro do projeto.")
    work_root.mkdir(exist_ok=True)
    base = work_root / f"pytest-{uuid4().hex}"

    if base.exists() or base.is_symlink():
        raise pytest.UsageError("O diretório temporário exclusivo já existe; execute novamente.")
    config.option.basetemp = str(base)
