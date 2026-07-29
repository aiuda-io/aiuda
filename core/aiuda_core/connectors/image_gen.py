"""Generación de imágenes — el motor visual de la plantilla de Contenido.

El texto de las publicaciones lo redacta el proveedor de IA (Claude/OpenAI); las IMÁGENES
salen de aquí. Es pluggable a propósito (el core es abierto): el dueño elige proveedor y trae
su credencial, cifrada por tenant. Tres vías, misma interfaz:

  fal      fal.ai corriendo modelos OPEN-WEIGHTS (Flux). La vía recomendada por costo: Flux
           [schnell] cuesta fracciones de centavo por imagen. Auth: `Authorization: Key <key>`.
  openai   Images API de OpenAI (gpt-image-1). Si el negocio ya tiene una API key de OpenAI,
           reusa esa relación. Más caro por imagen, pero sin cuenta nueva.
  custom   Cualquier endpoint COMPATIBLE con la Images API de OpenAI: tu propio ComfyUI/
           Stable Diffusion detrás de un gateway, u otro proveedor. base_url + api_key. La vía
           100% self-host (open source de verdad, sin pagar por imagen si tienes GPU).

Honestidad: la GENERACIÓN está cableada contra el contrato documentado de cada vía; la
plantilla de Contenido que la consume está Planeada. Conéctalo y `Probar conexión` valida de
verdad. Contrato fal: https://fal.ai/models/fal-ai/flux/schnell/api · OpenAI Images:
https://platform.openai.com/docs/api-reference/images
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("aiuda.image_gen")

VALID_PROVIDERS = ("fal", "openai", "custom")

# Modelos por defecto por vía. fal usa Flux schnell (open-weights, el más barato).
DEFAULT_MODEL = {
    "fal": "fal-ai/flux/schnell",
    "openai": "gpt-image-1",
    "custom": "",  # lo define el endpoint self-host
}

_OPENAI_BASE = "https://api.openai.com"
_FAL_BASE = "https://fal.run"


@dataclass
class ImagenGenerada:
    url: str
    provider: str
    model: str


class ImageGenError(RuntimeError):
    """Fallo generando imagen (credencial, red, o respuesta inválida del proveedor)."""


class ImageGenClient:
    """Cliente de generación de imágenes agnóstico al proveedor.

    ``provider`` decide el endpoint y la forma del request/response; la interfaz pública
    (``generate`` / ``test_connection``) es la misma para que la plantilla de Contenido no
    sepa de proveedores."""

    def __init__(
        self,
        provider: str = "fal",
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        if provider not in VALID_PROVIDERS:
            raise ImageGenError(f"Proveedor de imagen desconocido: {provider}")
        if not (api_key or "").strip():
            raise ImageGenError("Falta la API key del proveedor de imagen.")
        self.provider = provider
        self.api_key = api_key.strip()
        self.model = (model or "").strip() or DEFAULT_MODEL[provider]
        self.base_url = (base_url or "").strip() or self._default_base()
        if provider == "custom" and not self.base_url:
            raise ImageGenError("La vía 'custom' requiere el base_url de tu endpoint.")
        self._transport = transport

    def _default_base(self) -> str:
        if self.provider == "openai":
            return _OPENAI_BASE
        if self.provider == "fal":
            return _FAL_BASE
        return ""  # custom lo trae el dueño

    def _client(self) -> httpx.Client:
        auth = f"Key {self.api_key}" if self.provider == "fal" else f"Bearer {self.api_key}"
        return httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": auth, "Content-Type": "application/json"},
            timeout=httpx.Timeout(120.0, connect=15.0),
            transport=self._transport,
        )

    # -- generación ----------------------------------------------------------
    def generate(self, prompt: str, *, size: str = "1024x1024", n: int = 1) -> list[ImagenGenerada]:
        """Genera n imágenes desde el prompt. Devuelve URLs (o data URIs). Levanta
        ImageGenError con un mensaje honesto si el proveedor rechaza o no responde."""
        prompt = (prompt or "").strip()
        if not prompt:
            raise ImageGenError("El prompt de la imagen viene vacío.")
        try:
            with self._client() as http:
                if self.provider == "fal":
                    return self._gen_fal(http, prompt, size, n)
                return self._gen_openai(http, prompt, size, n)
        except httpx.HTTPError as exc:
            raise ImageGenError(f"No se pudo generar la imagen: {exc}") from exc

    def _gen_fal(self, http: httpx.Client, prompt: str, size: str, n: int) -> list[ImagenGenerada]:
        # fal recibe la RUTA del modelo como path; image_size acepta presets o {width,height}.
        body: dict = {"prompt": prompt, "num_images": n, "image_size": _fal_size(size)}
        resp = http.post(f"/{self.model}", json=body)
        resp.raise_for_status()
        data = resp.json()
        imgs = data.get("images") or []
        if not imgs:
            raise ImageGenError("fal no devolvió imágenes.")
        return [ImagenGenerada(url=i.get("url", ""), provider="fal", model=self.model) for i in imgs if i.get("url")]

    def _gen_openai(self, http: httpx.Client, prompt: str, size: str, n: int) -> list[ImagenGenerada]:
        # OpenAI Images (y endpoints compatibles): /v1/images/generations.
        body = {"model": self.model, "prompt": prompt, "size": size, "n": n}
        resp = http.post("/v1/images/generations", json=body)
        resp.raise_for_status()
        data = resp.json()
        out: list[ImagenGenerada] = []
        for d in data.get("data") or []:
            url = d.get("url") or (f"data:image/png;base64,{d['b64_json']}" if d.get("b64_json") else "")
            if url:
                out.append(ImagenGenerada(url=url, provider=self.provider, model=self.model))
        if not out:
            raise ImageGenError("El proveedor no devolvió imágenes.")
        return out

    # -- prueba de conexión --------------------------------------------------
    def test_connection(self) -> dict:
        """Valida la credencial contra el proveedor real.

        openai/custom: lista modelos (GET /v1/models) — no genera ni cuesta.
        fal: no expone un chequeo de auth sin costo, así que genera UNA imagen mínima con el
        modelo más barato (Flux schnell) — cuesta una fracción de centavo. Devuelve una señal
        para el semáforo."""
        with self._client() as http:
            if self.provider == "fal":
                imgs = self._gen_fal(http, "a small gray square, test", "512x512", 1)
                return {"provider": "fal", "model": self.model, "imagen": imgs[0].url}
            resp = http.get("/v1/models")
            resp.raise_for_status()
            data = resp.json()
            modelos = data.get("data") if isinstance(data, dict) else data
            return {"provider": self.provider, "modelos": len(modelos or [])}


def _fal_size(size: str) -> object:
    """Traduce '1024x1024' al formato de fal. Presets cuadrados usan el enum; otros, {w,h}."""
    presets = {
        "1024x1024": "square_hd",
        "512x512": "square",
        "1024x768": "landscape_4_3",
        "768x1024": "portrait_4_3",
    }
    if size in presets:
        return presets[size]
    try:
        w, h = (int(x) for x in size.lower().split("x"))
        return {"width": w, "height": h}
    except (ValueError, TypeError):
        return "square_hd"


def test_connection(creds: dict) -> dict:
    """Envoltura para el endpoint de integraciones (misma forma que los demás testers).
    Nunca relanza: veredicto honesto ok/False."""
    if not (creds.get("api_key") or "").strip():
        return {"ok": False, "message": "Falta la API key del proveedor de imagen."}
    try:
        info = ImageGenClient(
            provider=creds.get("provider") or "fal",
            api_key=creds["api_key"],
            base_url=creds.get("base_url"),
            model=creds.get("model"),
        ).test_connection()
    except Exception as exc:  # noqa: BLE001 — el test nunca tumba el endpoint
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}
    detalle = {"Modelos": info["modelos"]} if "modelos" in info else {"Imagen de prueba": "generada"}
    return {"ok": True, "message": f"Conectado a {info['provider']}.", "details": detalle}
