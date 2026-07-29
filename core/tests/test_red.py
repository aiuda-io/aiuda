"""Descubrimiento de una IA en la red local.

Ningún test toca la red: el inspector y las direcciones se inyectan. Lo que se
prueba es la lógica que le ahorra al dueño teclear una IP.
"""

from aiuda_core.engine import red


def test_subred_excluye_la_propia_y_da_254_direcciones():
    ips = red.subred("192.168.1.37")
    assert "192.168.1.37" not in ips
    assert "192.168.1.1" in ips and "192.168.1.254" in ips
    assert len(ips) == 253


def test_subred_ignora_una_ip_mal_formada():
    assert red.subred("no-es-una-ip") == []


def test_buscar_devuelve_lo_encontrado_y_ordena_por_utilidad():
    con_modelos = red.ServidorIA(
        ip="192.168.1.10", puerto=11434, equipo="Mac de Jose",
        base_url="http://192.168.1.10:11434/v1", programa="Ollama",
        modelos=["llama3.1:8b", "qwen2.5:7b"],
    )
    sin_modelos = red.ServidorIA(
        ip="192.168.1.20", puerto=1234, equipo="PC recepcion",
        base_url="http://192.168.1.20:1234/v1", programa="LM Studio", modelos=[],
    )
    protegido = red.ServidorIA(
        ip="192.168.1.30", puerto=1234, equipo="Servidor",
        base_url="http://192.168.1.30:1234/v1", programa="LM Studio", protegido=True,
    )
    hallazgos = {("192.168.1.10", 11434): con_modelos,
                 ("192.168.1.20", 1234): sin_modelos,
                 ("192.168.1.30", 1234): protegido}

    def inspector(ip, puerto):
        return hallazgos.get((ip, puerto))

    def puerto_abierto(objetivo):
        return objetivo in hallazgos

    original = red._puerto_abierto
    red._puerto_abierto = lambda ip, puerto, timeout=0.1: puerto_abierto((ip, puerto))
    try:
        encontrados = red.buscar(
            direcciones=["192.168.1.10", "192.168.1.20", "192.168.1.30"],
            inspector=inspector,
            hilos=4,
        )
    finally:
        red._puerto_abierto = original

    # El que ya trae modelos va primero; el que pide contraseña, al final.
    assert [s.equipo for s in encontrados] == ["Mac de Jose", "PC recepcion", "Servidor"]
    assert encontrados[0].base_url == "http://192.168.1.10:11434/v1"
    assert encontrados[-1].protegido is True


def test_buscar_sin_red_no_truena():
    assert red.buscar(direcciones=[], inspector=lambda *_: None) == []


def test_inspeccionar_reconoce_ollama(monkeypatch):
    def fake(url, timeout=0):
        if url.endswith("/api/tags"):
            return 200, {"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5:7b"}]}
        return 0, None

    monkeypatch.setattr(red, "_consultar", fake)
    monkeypatch.setattr(red, "_nombre_equipo", lambda ip: "Mac de Jose")
    s = red.inspeccionar("192.168.1.10", 11434)
    assert s is not None
    assert s.programa == "Ollama" and s.modelos == ["llama3.1:8b", "qwen2.5:7b"]
    assert s.base_url == "http://192.168.1.10:11434/v1"


def test_inspeccionar_reconoce_openai_compatible(monkeypatch):
    def fake(url, timeout=0):
        if url.endswith("/api/tags"):
            return 404, None
        return 200, {"data": [{"id": "gemma-3-12b"}]}

    monkeypatch.setattr(red, "_consultar", fake)
    monkeypatch.setattr(red, "_nombre_equipo", lambda ip: "PC recepcion")
    s = red.inspeccionar("192.168.1.20", 1234)
    assert s is not None and s.programa == "LM Studio" and s.modelos == ["gemma-3-12b"]


def test_inspeccionar_marca_protegido_sin_adivinar_credenciales(monkeypatch):
    """Un servidor con contraseña se reporta como tal: aiuda no intenta entrar."""

    def fake(url, timeout=0):
        return (404, None) if url.endswith("/api/tags") else (401, None)

    monkeypatch.setattr(red, "_consultar", fake)
    monkeypatch.setattr(red, "_nombre_equipo", lambda ip: "Servidor")
    s = red.inspeccionar("192.168.1.30", 1234)
    assert s is not None and s.protegido is True and s.modelos == []


def test_inspeccionar_ignora_lo_que_no_es_una_ia(monkeypatch):
    monkeypatch.setattr(red, "_consultar", lambda url, timeout=0: (200, {"otra": "cosa"}))
    monkeypatch.setattr(red, "_nombre_equipo", lambda ip: "x")
    assert red.inspeccionar("192.168.1.99", 11434) is None
