"""El contrato de /v1/setup/maquina y de la descarga de un modelo local.

Estos endpoints no tocan la base ni el workspace: son una foto de la
computadora del dueño. Aquí la computadora se finge (RAM, Ollama, PATH) para
que el contrato se pruebe siempre igual, corra donde corra el test.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aiuda_core.engine import maquina
from aiuda_server.api.main import app


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _sin_descargas_previas():
    maquina._descargas.clear()
    yield
    maquina._descargas.clear()


@pytest.fixture()
def mac_falsa(monkeypatch, tmp_path):
    """Una Mac de 24 GB con Ollama corriendo y el CLI de Claude instalado."""
    binarios = tmp_path / "bin"
    binarios.mkdir()
    claude = binarios / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(binarios))
    # HOME de mentiras: si no, la búsqueda fuera del PATH encontraría los CLIs
    # de verdad de la máquina donde corren los tests.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "casa"))

    monkeypatch.setattr(maquina, "chip", lambda: "Apple M1 Max")
    monkeypatch.setattr(maquina, "sistema_operativo", lambda: "macOS 15.2")
    monkeypatch.setattr(maquina, "ram_gb", lambda: 24.0)
    monkeypatch.setattr(maquina.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(maquina, "ruta_ollama", lambda: "/usr/local/bin/ollama")
    respuestas = {
        f"{maquina.OLLAMA_HOST}/api/tags": {
            "models": [{"name": "qwen2.5-coder:1.5b", "size": 986062089}]
        },
        f"{maquina.OLLAMA_HOST}/api/version": {"version": "0.5.4"},
    }
    monkeypatch.setattr(maquina, "_pedir_json", lambda url: respuestas.get(url))
    return claude


def test_maquina_devuelve_el_contrato(client, mac_falsa):
    datos = client.get("/v1/setup/maquina").json()

    assert datos["equipo"] == {
        "chip": "Apple M1 Max",
        "so": "macOS 15.2",
        "ram_gb": 24.0,
        "memoria_ia_gb": 16,
        "arquitectura": "arm64",
    }
    assert datos["ollama"] == {
        "instalado": True,
        "corriendo": True,
        "version": "0.5.4",
        "ruta": "/usr/local/bin/ollama",
    }
    assert datos["modelos_instalados"] == [{"nombre": "qwen2.5-coder:1.5b", "tam_gb": 1.0}]
    assert datos["clis"] == {
        "claude": {"instalado": True, "ruta": str(mac_falsa)},
        "codex": {"instalado": False, "ruta": None},
    }

    recomendados = datos["recomendados"]
    assert len(recomendados) >= 5
    assert [m for m in recomendados if m["recomendado"]][0] is recomendados[0]
    por_nombre = {m["nombre"]: m for m in recomendados}
    assert por_nombre["llama3.1:8b"]["cabe"] == "bien"
    assert por_nombre["llama3.1:8b"]["instalado"] is False
    assert por_nombre["qwen2.5:32b"]["cabe"] == "no"
    assert por_nombre["llama3.1:8b"]["para"]


def test_maquina_sin_ollama_igual_recomienda(client, monkeypatch):
    monkeypatch.setattr(maquina, "ram_gb", lambda: 16.0)
    monkeypatch.setattr(maquina, "ruta_ollama", lambda: None)
    monkeypatch.setattr(maquina, "_pedir_json", lambda url: None)

    datos = client.get("/v1/setup/maquina").json()

    assert datos["ollama"]["instalado"] is False
    assert datos["ollama"]["corriendo"] is False
    assert datos["modelos_instalados"] == []
    assert len(datos["recomendados"]) >= 5
    assert any(m["recomendado"] for m in datos["recomendados"])


def test_descargar_responde_202_y_no_lanza_dos_veces(client, monkeypatch):
    lanzados: list[str] = []
    # El hilo real correría `ollama pull`; aquí solo se registra que se lanzó.
    monkeypatch.setattr(maquina, "_correr_pull", lambda nombre: lanzados.append(nombre))

    primera = client.post("/v1/setup/modelo/descargar", json={"modelo": "llama3.1:8b"})
    segunda = client.post("/v1/setup/modelo/descargar", json={"modelo": "llama3.1:8b"})

    assert primera.status_code == 202
    assert primera.json()["estado"] == "descargando"
    assert segunda.status_code == 202
    assert lanzados == ["llama3.1:8b"]


def test_descargar_rechaza_nombre_raro(client):
    respuesta = client.post("/v1/setup/modelo/descargar", json={"modelo": "-rf /"})
    assert respuesta.status_code == 400
    assert "modelo" in respuesta.json()["detail"].lower()


def test_progreso_de_una_descarga_en_curso(client, monkeypatch):
    monkeypatch.setattr(maquina, "_correr_pull", lambda nombre: None)
    client.post("/v1/setup/modelo/descargar", json={"modelo": "llama3.1:8b"})

    datos = client.get("/v1/setup/modelo/progreso", params={"modelo": "llama3.1:8b"}).json()

    assert datos == {
        "estado": "descargando",
        "porcentaje": 0,
        "detalle": "Preparando la descarga.",
    }


def test_progreso_de_algo_que_nadie_pidio(client, monkeypatch):
    monkeypatch.setattr(maquina, "_pedir_json", lambda url: None)

    datos = client.get("/v1/setup/modelo/progreso", params={"modelo": "llama3.1:8b"}).json()

    assert datos["estado"] == "desconocido"
    assert datos["porcentaje"] == 0
