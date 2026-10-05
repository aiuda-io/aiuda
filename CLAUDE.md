# CLAUDE.md: aiuda

Qué es aiuda, el stack y cómo se trabaja aquí. Lee también `VISION.md` (por qué
existe) y `ARCHITECTURE.md` (cómo está armado).

## La idea

aiuda automatiza el back office de la PyME mexicana con **ayudantes**: agentes de
IA con **humano en el loop (HITL)**. El ayudante lee tus fuentes (Odoo, CFDIs,
Excel, WhatsApp, tu propia API), **propone** acciones (recordatorios de cobro,
respuestas, conciliaciones) y **tú apruebas** antes de que salga nada.

Es una herramienta **local-first y abierta (Apache-2.0)**: corre en la
computadora del negocio, desde la app de escritorio o con `aiuda start`. Sin
cuentas, sin nube, sin telemetría. Cobranza es el vertical más maduro.

Principios que mandan sobre cualquier feature:

- **Tus fuentes siguen mandando; aiuda actúa encima.** Procedencia en cada dato;
  el write-back regresa a la fuente.
- **Honestidad brutal.** Si algo es un no-op o "se cablea después", se dice en la
  UI y en el commit. Nada de vender lo que no corre.
- **Soberanía humana.** Los tools de chat son solo lectura; para actuar, los
  agentes proponen y el humano aprueba. Eso no se debilita en ningún PR.
- **KISS, anti-slop.** Reestructurar información, no decorar.

## Stack

- **Backend (Python 3.11+, FastAPI).** `core/aiuda_core/` = dominio sin HTTP
  (modelos, motor, conectores, CUA, cripto). `server/aiuda_server/` = API local,
  jobs, scheduler y CLI (`aiuda`). SQLite en `~/.aiuda/` por default (los tests
  corren sobre SQLite en memoria); sin Alembic: el esquema vive en los modelos y
  `create_all` es idempotente. **Evita migraciones**: config nueva va en
  `Tenant.config` (JSON).
- **Frontend (`web/`):** Next.js 16 (App Router). OJO: no es el Next que conoces,
  lee `node_modules/next/dist/docs/` antes de escribir. Tailwind v4, tokens
  OKLCH, **tema claro únicamente**. En producción es export ESTÁTICO servido por
  FastAPI: **no hay segmentos dinámicos de ruta**, los detalles van por query
  (`/clientes/detalle?id=…`).
- **Escritorio (`desktop/`):** Tauri. Solo ventana y ciclo de vida del sidecar;
  el binario del server lo arma PyInstaller con `packaging/aiuda.spec`.
- **IA:** BYO vía `engine/provider.py` y `engine/runner.py` (Protocol). Tres vías,
  todas legítimas: la llave del dueño (Claude u OpenAI), el CLI que YA tiene
  instalado (`claude_cli`/`codex_cli`: lo lanzamos como subproceso y se autentica con
  SU sesión, aiuda nunca ve su token), y "local" (OpenAI-compatible: Ollama). **No
  hay modo suscripción**: se retiró porque exigía declararse como el cliente oficial
  del proveedor para que aceptara el token, y eso no se reparte en Apache-2.0. El
  metering y el tope se enganchan en `server/aiuda_server/metering.py`.
- **WhatsApp:** wacli (tu número, protocolo WhatsApp Web). La consola lo instala
  con un clic (`connectors/wacli_bin.py`) y el server es dueño del
  `wacli sync --follow` (`server/aiuda_server/wacli_sync.py`): lo arranca, lo
  relanza y lo apaga; los envíos se le delegan, no lo detienen. El sondeo entrante
  es in-process (`server/aiuda_server/inbound.py`) y **solo se atiende a clientes
  del negocio y al dueño**: el número suele ser el personal, así que lo de
  cualquier otro número no se lee, no se guarda y no recibe respuesta. Correo
  IMAP/SMTP; la Cloud API oficial requiere una URL pública que la instalación
  local no trae, y está oculta del catálogo hasta estrenarla.
- **Integraciones:** el catálogo (`server/aiuda_server/api/integrations.py`) declara
  `estrenada` por integración; `False` = nadie la ha usado con una cuenta real y la
  consola le pone el sello "Sin estrenar". `oculta` = no se ofrece hasta probarse.
- **Teléfono:** la app de iPhone vive en un repo aparte (`aiuda-ios`). Se empareja por
  QR con la segunda puerta de la red local (`server/aiuda_server/red_local.py`); cada
  endpoint nuevo se declara en `server/aiuda_server/api/permisos.py`.
- **Solo Mac, solo SQLite.** No hay instalador para Windows ni Linux, ni otro motor
  de base.

## Correr local

```bash
uv sync && uv run python scripts/seed.py
uv run aiuda start --no-token          # todo en 127.0.0.1:4747
# o con recarga: scripts/dev.sh  (API :8000 + Next :3000)
# extras: uv sync --extra cua && .venv/bin/playwright install chromium
```

Gate antes de commitear: `uv run pytest` (todo verde, sin API key),
`uv run ruff check .`, `cd web && npm run lint && npx tsc --noEmit && npm run export`.

## Documentación

`docs/` es para el dueño del negocio: INSTALAR, IA, APARATOS, DATOS, SAT,
PROBLEMAS, CUA. La raíz es para quien desarrolla: README, ARCHITECTURE, VISION,
CONTRIBUTING, RELEASING. Un tema, un documento. Si un cambio hace que un
documento mienta, se arregla en el mismo PR.

Ese `docs/` **es** el manual que sirve la consola: `web/scripts/manual.mjs` lo
convierte a `web/public/manual/` antes de cada build y el export lo lleva a
`out/`. No se escribe documentación en `web/`: se escribe markdown en `docs/`.

## Convenciones (duras)

- **Diseño:** KISS, tema claro, cero gradientes y glows, cero emojis, sin em
  dashes. Clickabilidad total, trazabilidad, procedencia visible.
- **Seguridad:** nunca secretos en claro (cifrado Fernet, llave en
  `~/.aiuda/key`); jamás manejar contraseñas del usuario (el handoff del CUA
  existe para eso).
- **Honestidad:** todo feature nombra el resultado que mueve; los no-ops se
  marcan en UI y commit.
- **Git:** commits en español, imperativos, sin atribución de IA.
