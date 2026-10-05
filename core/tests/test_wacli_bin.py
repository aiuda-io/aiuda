"""Resolver e instalar wacli: ruta absoluta siempre, y nada se guarda sin que la
suma coincida. Sin red: la descarga se inyecta."""

import hashlib
import io
import os
import tarfile

import pytest

from aiuda_core.connectors import wacli_bin
from aiuda_core.connectors.wacli import WacliClient, WacliError


def _tar_con(nombre: str, contenido: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(nombre)
        info.size = len(contenido)
        tar.addfile(info, io.BytesIO(contenido))
    return buf.getvalue()


@pytest.fixture()
def carpeta(tmp_path, monkeypatch):
    monkeypatch.setattr(wacli_bin, "ruta_instalada", lambda: tmp_path / "bin" / "wacli")
    monkeypatch.setattr(wacli_bin, "_macos_mayor", lambda: 15)
    monkeypatch.setattr(wacli_bin, "_arquitectura", lambda: "arm64")
    return tmp_path


def test_resolver_prefiere_el_explicito(monkeypatch, carpeta):
    monkeypatch.setattr(wacli_bin.settings, "wacli_bin", "/opt/otro/wacli")
    monkeypatch.setattr(wacli_bin, "_del_sistema", lambda: "/opt/homebrew/bin/wacli")
    assert wacli_bin.resolver() == "/opt/otro/wacli"


def test_resolver_el_instalado_por_aiuda_gana_al_del_sistema(monkeypatch, carpeta):
    monkeypatch.setattr(wacli_bin, "_del_sistema", lambda: "/opt/homebrew/bin/wacli")
    assert wacli_bin.resolver() == "/opt/homebrew/bin/wacli"  # aún no hay propio
    propio = carpeta / "bin" / "wacli"
    propio.parent.mkdir()
    propio.write_text("#!/bin/sh\n")
    propio.chmod(0o755)
    assert wacli_bin.resolver() == str(propio)


def test_resolver_sin_ninguno_es_none(carpeta):
    assert wacli_bin.resolver() is None


def test_instalar_verifica_la_suma_y_deja_ejecutable(monkeypatch, carpeta):
    # Así viene en el release real: con "./" por delante.
    paquete = _tar_con("./wacli", b"#!/bin/sh\necho wacli 0.20.0\n")
    monkeypatch.setitem(wacli_bin.WACLI_SHA256, "arm64", hashlib.sha256(paquete).hexdigest())
    pedidas = []

    def descargar(url):
        pedidas.append(url)
        return paquete

    ruta = wacli_bin.instalar(descargar)
    assert pedidas == [
        "https://github.com/openclaw/wacli/releases/download/v0.20.0/"
        "wacli_0.20.0_darwin_arm64.tar.gz"
    ]
    assert ruta == str(carpeta / "bin" / "wacli")
    assert os.access(ruta, os.X_OK)
    assert wacli_bin.resolver() == ruta
    assert wacli_bin.version(ruta) == "0.20.0"
    assert not (carpeta / "bin" / "wacli.descargando").exists()


def test_instalar_con_suma_distinta_no_guarda_nada(carpeta):
    # La suma fijada es la del release real: cualquier otro contenido se rechaza.
    with pytest.raises(wacli_bin.WacliInstallError, match="No se pudo descargar"):
        wacli_bin.instalar(lambda url: _tar_con("wacli", b"alterado"))
    assert not (carpeta / "bin").exists()


def test_instalar_sin_red_avisa_en_espanol(carpeta):
    def sin_red(url):
        raise OSError("dns")

    with pytest.raises(wacli_bin.WacliInstallError, match="Revisa tu internet"):
        wacli_bin.instalar(sin_red)


def test_instalar_en_macos_viejo_se_niega_sin_descargar(monkeypatch, carpeta):
    monkeypatch.setattr(wacli_bin, "_macos_mayor", lambda: 14)
    with pytest.raises(wacli_bin.WacliInstallError, match="macOS 15"):
        wacli_bin.instalar(lambda url: pytest.fail("no debe descargar"))


def test_enviar_sin_wacli_instalado_avisa_en_espanol(monkeypatch, carpeta):
    monkeypatch.setattr(wacli_bin.settings, "wacli_bin", "/no/existe/wacli")
    with pytest.raises(WacliError, match="Falta instalar el conector de WhatsApp"):
        WacliClient().send_text("5213314872210", "hola")
