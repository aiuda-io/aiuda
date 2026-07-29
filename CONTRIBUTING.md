# Contribuir a aiuda

Gracias por el interés. Antes de escribir código, lee [VISION.md](VISION.md): las
contribuciones se evalúan contra esos principios (local-first, soberanía humana,
procedencia de datos, honestidad, KISS).

## Setup de desarrollo

```bash
uv sync                           # backend (SQLite local, sin Docker)
uv run python scripts/seed.py     # datos demo deterministas
uv run aiuda start --no-token     # API y consola en 127.0.0.1:4747
```

Para trabajar la consola con recarga en vivo (dos procesos, mismo origen vía
rewrite):

```bash
scripts/dev.sh          # API :8000 con reload + Next :3000
scripts/dev.sh down     # detener ambos
```

Extras opcionales: `uv sync --extra cua` más
`.venv/bin/playwright install chromium` para el CUA. Para la app de escritorio
necesitas además node y Rust: `scripts/build-app.sh`.

La IA se conecta desde la consola (/proveedor): API key, suscripción o un modelo
local con Ollama. Los tests no necesitan ninguna (el LLM va mockeado).

## Antes de abrir un PR

```bash
uv run pytest          # suite completa, determinista
uv run ruff check .
cd web && npx tsc --noEmit && npm run export
```

- PRs chicos y enfocados. Un cambio, un PR. Cumple la plantilla (tests verdes,
  cero emojis, español, sin secretos).
- Los safeguards de los agentes (humano en el loop, máquina de estados de
  aprobación, fact-check de pagos) no se debilitan en ningún PR. Punto.
- Nada de migraciones: el esquema vive en los modelos y `create_all` lo
  materializa. La configuración nueva va en `Tenant.config`.
- UI: sigue `web/DESIGN.md` (tokens OKLCH, tema claro, cero decoración).
- Si tu cambio hace que un documento mienta, arregla el documento en el mismo PR.
- Texto de producto en español mexicano; código y commits en el idioma que
  prefieras.

## Reportar y convivir

- Errores y propuestas: abre un issue (hay plantillas). Las preguntas van a
  [Discussions](https://github.com/aiuda-io/aiuda/discussions).
- Vulnerabilidades: **no** abras un issue público, sigue [SECURITY.md](SECURITY.md).
- Al participar aceptas el [Código de conducta](CODE_OF_CONDUCT.md).

## Dónde empezar

- Issues etiquetados `good first issue`.
- Conectores nuevos: la interfaz está en `core/aiuda_core/connectors/` y el
  catálogo en `server/aiuda_server/api/integrations.py`.
- Estrenar en vivo los conectores que hoy dicen "implementado contra el contrato
  documentado" en la consola (Slack, Twilio, Google Sheets, Mercado Libre,
  Mercado Pago, Clip, Conekta, WhatsApp Cloud) y aportar los fixtures.
- Probar los instaladores de Windows y Linux, que se construyen pero nadie ha
  corrido.
- Firma y notarización de los instaladores.

## Licencia

Al contribuir aceptas que tu aportación se licencia bajo Apache-2.0,
© Hanova Consulting.
