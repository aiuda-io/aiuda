"""Conector de generación de imágenes (plantilla de Contenido), pluggable y con transporte
mockeado. Ninguno toca la red: httpx.MockTransport intercepta todo."""

import httpx
import pytest

from aiuda_core.connectors.image_gen import (
    ImageGenClient,
    ImageGenError,
    _fal_size,
)
from aiuda_core.connectors.image_gen import test_connection as wrapper_test


def _t(handler):
    return httpx.MockTransport(handler)


def test_fal_generate_url_auth_y_parseo():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"images": [{"url": "https://cdn.fal/img1.png"}]})

    c = ImageGenClient(provider="fal", api_key="k-fal", transport=_t(handler))
    out = c.generate("un taco al pastor", size="1024x1024")
    assert out[0].url == "https://cdn.fal/img1.png" and out[0].provider == "fal"
    assert "fal-ai/flux/schnell" in captured["url"]
    assert captured["auth"] == "Key k-fal"  # fal usa 'Key', no 'Bearer'


def test_openai_generate_bearer_y_b64():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"data": [{"b64_json": "QUJD"}]})

    c = ImageGenClient(provider="openai", api_key="sk-oa", transport=_t(handler))
    out = c.generate("una jarra de agua fresca")
    assert out[0].url.startswith("data:image/png;base64,QUJD")
    assert captured["url"].endswith("/v1/images/generations")
    assert captured["auth"] == "Bearer sk-oa"


def test_custom_requiere_base_url():
    with pytest.raises(ImageGenError):
        ImageGenClient(provider="custom", api_key="k")  # sin base_url


def test_custom_usa_su_endpoint():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["host"] = request.url.host
        return httpx.Response(200, json={"data": [{"url": "https://mi-sd/out.png"}]})

    c = ImageGenClient(provider="custom", api_key="k", base_url="https://mi-sd", model="sdxl", transport=_t(handler))
    out = c.generate("logo minimal")
    assert out[0].url == "https://mi-sd/out.png" and captured["host"] == "mi-sd"


def test_provider_desconocido_y_sin_key():
    with pytest.raises(ImageGenError):
        ImageGenClient(provider="midjourney", api_key="k")
    with pytest.raises(ImageGenError):
        ImageGenClient(provider="fal", api_key="")


def test_test_connection_openai_lista_modelos():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/models") and request.method == "GET"
        return httpx.Response(200, json={"data": [{"id": "gpt-image-1"}, {"id": "dall-e-3"}]})

    info = ImageGenClient(provider="openai", api_key="sk", transport=_t(handler)).test_connection()
    assert info["modelos"] == 2 and info["provider"] == "openai"


def test_test_connection_fal_genera_minima():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"images": [{"url": "https://cdn.fal/test.png"}]})

    info = ImageGenClient(provider="fal", api_key="k", transport=_t(handler)).test_connection()
    assert info["imagen"] == "https://cdn.fal/test.png"


def test_wrapper_sin_key_y_error_honesto():
    assert wrapper_test({"provider": "fal"})["ok"] is False

    # Con key y un transporte que responde, el wrapper NO puede inyectar transport (usa el
    # cliente real), así que probamos la rama de credencial faltante y la forma del error.
    bad = wrapper_test({"provider": "openai", "api_key": "x", "base_url": "http://127.0.0.1:1"})
    assert bad["ok"] is False and "No se pudo conectar" in bad["message"]


def test_fal_size_presets_y_dimensiones():
    assert _fal_size("1024x1024") == "square_hd"
    assert _fal_size("640x480") == {"width": 640, "height": 480}
    assert _fal_size("raro") == "square_hd"
