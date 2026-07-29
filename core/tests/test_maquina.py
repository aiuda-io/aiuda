"""La detección de la máquina y la recomendación de modelos locales.

La salida de `ollama pull` que se usa aquí (core/tests/data/ollama_pull.txt) es
una GRABACIÓN real: se corrió `ollama pull all-minilm` en una Mac, se guardó su
salida cruda (con los códigos de la terminal incluidos) y se borró el modelo.
Ningún test descarga nada.
"""

import threading
from pathlib import Path

import pytest

from aiuda_core.engine import maquina

SALIDA_PULL = Path(__file__).parent / "data" / "ollama_pull.txt"


@pytest.fixture()
def salida_pull() -> str:
    return SALIDA_PULL.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(autouse=True)
def _sin_descargas_previas():
    """Cada test empieza sin descargas registradas (el registro es de proceso)."""
    maquina._descargas.clear()
    yield
    maquina._descargas.clear()


# --- Memoria y "cabe" -----------------------------------------------------------------


def test_memoria_para_ia_es_dos_tercios_de_la_ram():
    assert maquina.memoria_para_ia(24) == 16
    assert maquina.memoria_para_ia(18) == 12
    assert maquina.memoria_para_ia(8) == 5


def test_memoria_para_ia_sin_ram_no_inventa():
    assert maquina.memoria_para_ia(None) is None
    assert maquina.memoria_para_ia(0) is None


def test_como_cabe_por_umbrales():
    # 16 GB para IA: hasta 9.6 GB cabe bien, hasta 14.4 cabe justo, arriba no.
    assert maquina.como_cabe(4.9, 16) == "bien"
    assert maquina.como_cabe(9.5, 16) == "bien"
    assert maquina.como_cabe(9.7, 16) == "justo"
    assert maquina.como_cabe(14.3, 16) == "justo"
    assert maquina.como_cabe(14.5, 16) == "no"
    assert maquina.como_cabe(19.9, 16) == "no"


def test_como_cabe_sin_memoria_dice_desconocido():
    assert maquina.como_cabe(4.9, None) == "desconocido"


# --- Catálogo -------------------------------------------------------------------------


def test_catalogo_ordena_los_que_caben_primero_y_recomienda_uno():
    recomendados = maquina.recomendar_modelos(16)

    assert [m["cabe"] for m in recomendados] == sorted(
        (m["cabe"] for m in recomendados), key=lambda c: maquina.ORDEN_CABE[c]
    )
    marcados = [m for m in recomendados if m["recomendado"]]
    assert len(marcados) == 1
    assert marcados[0]["cabe"] == "bien"
    # Con 16 GB para IA el mejor que cabe bien es qwen2.5:14b (9.0 GB).
    assert marcados[0]["nombre"] == "qwen2.5:14b"
    assert recomendados[0]["recomendado"] is True


def test_catalogo_completo_y_con_texto_de_dueno():
    recomendados = maquina.recomendar_modelos(16)
    assert len(recomendados) == len(maquina.CATALOGO) >= 5
    for modelo in recomendados:
        assert set(modelo) == {
            "nombre",
            "tam_gb",
            "cabe",
            "instalado",
            "recomendado",
            "para",
        }
        assert modelo["para"].endswith(".")


def test_maquina_chica_recomienda_lo_que_apenas_cabe():
    # 3 GB para IA: nada cabe bien; el ligero (2.0 GB) cabe justo y es el que se marca.
    recomendados = maquina.recomendar_modelos(3)
    marcados = [m for m in recomendados if m["recomendado"]]
    assert [m["nombre"] for m in marcados] == ["llama3.2:3b"]
    assert marcados[0]["cabe"] == "justo"


def test_maquina_minima_no_recomienda_nada():
    recomendados = maquina.recomendar_modelos(1)
    assert {m["cabe"] for m in recomendados} == {"no"}
    assert not any(m["recomendado"] for m in recomendados)


def test_sin_memoria_conocida_no_recomienda_nada():
    recomendados = maquina.recomendar_modelos(None)
    assert {m["cabe"] for m in recomendados} == {"desconocido"}
    assert not any(m["recomendado"] for m in recomendados)


def test_marca_los_ya_instalados():
    recomendados = maquina.recomendar_modelos(16, ["llama3.1:8b", "qwen2.5-coder:1.5b"])
    por_nombre = {m["nombre"]: m for m in recomendados}
    assert por_nombre["llama3.1:8b"]["instalado"] is True
    assert por_nombre["qwen2.5:7b"]["instalado"] is False


def test_instalado_sin_etiqueta_es_el_mismo_modelo():
    assert maquina._normalizar("llama3.1") == "llama3.1:latest"
    recomendados = maquina.recomendar_modelos(16, ["mistral-nemo:12b"])
    por_nombre = {m["nombre"]: m for m in recomendados}
    assert por_nombre["mistral-nemo:12b"]["instalado"] is True


def test_modelos_de_tags_traduce_bytes_a_gb():
    tags = {"models": [{"name": "qwen2.5-coder:1.5b", "size": 986062089}, {"name": ""}]}
    assert maquina.modelos_de_tags(tags) == [{"nombre": "qwen2.5-coder:1.5b", "tam_gb": 1.0}]
    assert maquina.modelos_de_tags(None) == []


# --- Ollama ---------------------------------------------------------------------------


def test_ollama_apagado_se_reporta_honesto(monkeypatch):
    monkeypatch.setattr(maquina, "ruta_ollama", lambda: None)
    monkeypatch.setattr(maquina, "_pedir_json", lambda url: None)

    ollama, instalados = maquina.detectar_ollama()

    assert ollama == {"instalado": False, "corriendo": False, "version": None, "ruta": None}
    assert instalados == []


def test_ollama_corriendo_reporta_version_y_modelos(monkeypatch):
    monkeypatch.setattr(maquina, "ruta_ollama", lambda: "/usr/local/bin/ollama")
    respuestas = {
        f"{maquina.OLLAMA_HOST}/api/tags": {
            "models": [{"name": "qwen2.5-coder:1.5b", "size": 986062089}]
        },
        f"{maquina.OLLAMA_HOST}/api/version": {"version": "0.5.4"},
    }
    monkeypatch.setattr(maquina, "_pedir_json", lambda url: respuestas.get(url))

    ollama, instalados = maquina.detectar_ollama()

    assert ollama == {
        "instalado": True,
        "corriendo": True,
        "version": "0.5.4",
        "ruta": "/usr/local/bin/ollama",
    }
    assert instalados == [{"nombre": "qwen2.5-coder:1.5b", "tam_gb": 1.0}]


# --- CLIs de IA -----------------------------------------------------------------------


def test_detecta_los_clis_del_path(monkeypatch, tmp_path):
    binarios = tmp_path / "bin"
    binarios.mkdir()
    falso = binarios / "claude"
    falso.write_text("#!/bin/sh\n")
    falso.chmod(0o755)
    monkeypatch.setenv("PATH", str(binarios))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "sin-nada"))

    clis = maquina.detectar_clis()

    assert clis["claude"] == {"instalado": True, "ruta": str(falso)}
    assert clis["codex"] == {"instalado": False, "ruta": None}


def test_detecta_los_clis_aunque_el_path_este_pelado(monkeypatch, tmp_path):
    """Como arranca la app de escritorio: PATH mínimo de macOS, CLI en ~/.local/bin."""
    binarios = tmp_path / ".local" / "bin"
    binarios.mkdir(parents=True)
    falso = binarios / "codex"
    falso.write_text("#!/bin/sh\n")
    falso.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    clis = maquina.detectar_clis()

    assert clis["codex"] == {"instalado": True, "ruta": str(falso)}
    assert clis["claude"]["instalado"] is False


# --- Progreso de `ollama pull` --------------------------------------------------------


def test_pull_completo_queda_listo(salida_pull):
    assert maquina.parsear_salida_pull(salida_pull) == {
        "estado": "listo",
        "porcentaje": 100,
        "detalle": "Listo: el modelo ya está en esta computadora.",
    }


def test_pull_a_medias_reporta_el_avance_de_la_capa_pesada(salida_pull):
    # La misma grabación, cortada donde la capa de los pesos iba en 57%.
    corte = salida_pull.index(" 57%")
    fin = min(k for k in (salida_pull.find("\r", corte), salida_pull.find("\n", corte)) if k != -1)

    progreso = maquina.parsear_salida_pull(salida_pull[:fin])

    assert progreso["estado"] == "descargando"
    assert progreso["porcentaje"] == 57
    assert progreso["detalle"] == "Descargando el modelo: 26 MB de 45 MB"


def test_pull_al_arranque_dice_que_prepara():
    progreso = maquina.parsear_salida_pull("pulling manifest ⠙")
    assert progreso == {
        "estado": "descargando",
        "porcentaje": 0,
        "detalle": "Preparando la descarga.",
    }


def test_pull_con_error_lo_dice_tal_cual():
    progreso = maquina.parsear_salida_pull("Error: pull model manifest: file does not exist")
    assert progreso["estado"] == "error"
    assert progreso["detalle"] == (
        "Ollama no pudo descargarlo: pull model manifest: file does not exist"
    )


def test_pull_verificando_no_dice_que_ya_acabo(salida_pull):
    corte = salida_pull.index("verifying")
    progreso = maquina.parsear_salida_pull(salida_pull[: corte + len("verifying sha256 digest")])
    assert progreso["estado"] == "descargando"
    assert progreso["detalle"] == "Verificando lo que se descargó."


# --- Descarga en hilo -----------------------------------------------------------------


class _SalidaEnPausa:
    """Un pipe falso: la grabación no "llega" hasta que el test suelta el freno.

    Así se puede mirar la descarga a la mitad, que es cuando importa la
    idempotencia (dos clics seguidos en Descargar no deben lanzar dos pulls).
    """

    def __init__(self, datos: bytes, soltar: threading.Event):
        self._datos = datos
        self._soltar = soltar
        self._entregado = False

    def read1(self, _n: int = 4096) -> bytes:
        if self._entregado:
            return b""
        self._soltar.wait(5)
        self._entregado = True
        return self._datos


class _ProcesoFalso:
    def __init__(self, salida: _SalidaEnPausa):
        self.stdout = salida

    def wait(self) -> int:
        return 0


@pytest.fixture()
def pull_falso(monkeypatch, salida_pull):
    """Sustituye `ollama pull` por la grabación, sin tocar la red ni el disco."""
    soltar = threading.Event()
    llamadas: list[list[str]] = []

    def _popen(cmd, **_kwargs):
        llamadas.append(cmd)
        return _ProcesoFalso(_SalidaEnPausa(salida_pull.encode("utf-8"), soltar))

    monkeypatch.setattr(maquina, "ruta_ollama", lambda: "/usr/local/bin/ollama")
    monkeypatch.setattr(maquina.subprocess, "Popen", _popen)
    yield llamadas, soltar
    # Los hilos de descarga no deben sobrevivir al test y ensuciar al siguiente.
    soltar.set()
    for nombre in list(maquina._descargas):
        _esperar_a_que_no_este("descargando", nombre)


def _esperar(nombre: str, estado: str, segundos: float = 5.0) -> dict:
    """Sondea el progreso hasta que llegue al estado esperado (o se acabe el tiempo)."""
    reloj = threading.Event()
    ultimo: dict = {}
    for _ in range(int(segundos * 100)):
        ultimo = maquina.progreso_descarga(nombre)
        if ultimo["estado"] == estado:
            return ultimo
        reloj.wait(0.01)
    return ultimo


def _esperar_a_que_no_este(estado: str, nombre: str, segundos: float = 5.0) -> None:
    reloj = threading.Event()
    for _ in range(int(segundos * 100)):
        if maquina._descargas.get(nombre, {}).get("estado") != estado:
            return
        reloj.wait(0.01)


def test_descargar_modelo_publica_avance_y_termina_listo(pull_falso):
    llamadas, soltar = pull_falso

    inicial = maquina.descargar_modelo("llama3.1:8b")

    assert inicial["estado"] == "descargando"
    assert llamadas == [["/usr/local/bin/ollama", "pull", "llama3.1:8b"]]
    soltar.set()
    assert _esperar("llama3.1:8b", "listo") == {
        "estado": "listo",
        "porcentaje": 100,
        "detalle": "Listo: el modelo ya está en esta computadora.",
    }


def test_descargar_modelo_no_lanza_dos_veces_el_mismo(pull_falso):
    llamadas, _soltar = pull_falso

    maquina.descargar_modelo("llama3.1:8b")
    segunda = maquina.descargar_modelo("llama3.1:8b")

    assert segunda["estado"] == "descargando"
    assert len(llamadas) == 1


def test_descargar_modelo_rechaza_nombres_raros():
    with pytest.raises(ValueError):
        maquina.descargar_modelo("-rf /")
    with pytest.raises(ValueError):
        maquina.descargar_modelo("")


def test_progreso_de_algo_que_nadie_pidio(monkeypatch):
    monkeypatch.setattr(maquina, "_pedir_json", lambda url: None)
    assert maquina.progreso_descarga("llama3.1:8b") == {
        "estado": "desconocido",
        "porcentaje": 0,
        "detalle": "Nadie ha pedido descargar este modelo en esta sesión.",
    }


def test_progreso_de_un_modelo_que_ya_estaba(monkeypatch):
    tags = {"models": [{"name": "llama3.1:8b", "size": 4900000000}]}
    monkeypatch.setattr(maquina, "_pedir_json", lambda url: tags)
    progreso = maquina.progreso_descarga("llama3.1:8b")
    assert progreso["estado"] == "listo"
    assert progreso["detalle"] == "Ya estaba instalado en esta computadora."


def test_sin_ollama_la_descarga_falla_honesta(monkeypatch):
    monkeypatch.setattr(maquina, "ruta_ollama", lambda: None)

    maquina.descargar_modelo("llama3.1:8b")

    fin = _esperar("llama3.1:8b", "error")
    assert fin["detalle"] == "No encontramos Ollama en esta computadora."
