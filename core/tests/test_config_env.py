"""Las variables propias de aiuda aceptan su nombre corto y el prefijado.

Los docs prometían `AIUDA_SCHEDULER_ENABLED` y no hacía nada: quien la usara
habría dejado el scheduler corriendo creyendo lo contrario. Ahora valen las dos
formas, y el prefijo es el que no choca con otras herramientas del sistema.
"""

import pytest
from aiuda_core.config import Settings


@pytest.mark.parametrize(
    "variable",
    ["SCHEDULER_ENABLED", "AIUDA_SCHEDULER_ENABLED"],
)
def test_scheduler_se_apaga_con_cualquiera_de_los_dos_nombres(monkeypatch, variable):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("AIUDA_SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv(variable, "false")
    assert Settings(_env_file=None).scheduler_enabled is False


@pytest.mark.parametrize("variable", ["WORKSPACE_ID", "AIUDA_WORKSPACE_ID"])
def test_workspace_id_acepta_ambos(monkeypatch, variable):
    monkeypatch.delenv("WORKSPACE_ID", raising=False)
    monkeypatch.delenv("AIUDA_WORKSPACE_ID", raising=False)
    monkeypatch.setenv(variable, "wk-123")
    assert Settings(_env_file=None).workspace_id == "wk-123"


@pytest.mark.parametrize("variable", ["SESSION_TOKEN", "AIUDA_SESSION_TOKEN"])
def test_session_token_acepta_ambos(monkeypatch, variable):
    """La app de escritorio pasa AIUDA_SESSION_TOKEN: si no se leyera, la
    ventana abriría con un token que el server no reconoce."""
    monkeypatch.delenv("SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AIUDA_SESSION_TOKEN", raising=False)
    monkeypatch.setenv(variable, "t0k3n")
    assert Settings(_env_file=None).session_token == "t0k3n"


@pytest.mark.parametrize("variable", ["DATABASE_URL", "AIUDA_DATABASE_URL"])
def test_database_url_acepta_ambos(monkeypatch, variable):
    """Apuntar la base a otro lado y que se ignore en silencio es de lo peor que
    puede pasar: crees estar en una base de prueba y estás escribiendo en la de
    verdad. (Pasó de verdad durante el desarrollo.)"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AIUDA_DATABASE_URL", raising=False)
    monkeypatch.setenv(variable, "sqlite:////tmp/otra.db")
    assert Settings(_env_file=None).database_url == "sqlite:////tmp/otra.db"


@pytest.mark.parametrize("variable", ["ANTHROPIC_API_KEY", "AIUDA_ANTHROPIC_API_KEY"])
def test_anthropic_api_key_acepta_ambos(monkeypatch, variable):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AIUDA_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv(variable, "sk-ant-prueba")
    assert Settings(_env_file=None).anthropic_api_key == "sk-ant-prueba"
