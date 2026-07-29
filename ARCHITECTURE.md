# Arquitectura

Un proceso, un puerto, tu computadora. Sin cuentas, sin nube, sin telemetría.

```
app de escritorio (Tauri)          o          aiuda start (terminal)
  └─ arranca el mismo server como sidecar        └─ el mismo server
                       │
                       ▼
              proceso Python único
              ├─ FastAPI en 127.0.0.1:4747 (token de sesión por arranque)
              ├─ consola: export estático de Next servido por el mismo proceso
              ├─ scheduler (hilos): corrida horaria + WhatsApp entrante (wacli)
              ├─ SQLite ~/.aiuda/aiuda.db (WAL); Postgres opcional (operadores)
              ├─ llave Fernet en ~/.aiuda/key (0600), una sola fuente
              ├─ IA BYO: Claude / OpenAI / local (Ollama, OpenAI-compatible)
              └─ CUA: Chromium local (Playwright) que opera portales; el dueño
                 hace el login él mismo (handoff) y la sesión queda cifrada
```

La app de escritorio no reimplementa nada: es una ventana sobre el server local
más el ciclo de vida (arrancarlo al abrir, apagarlo al cerrar). Por eso lo que
funciona en la terminal funciona en la app, y al revés.

## Paquetes

| Dir | Qué es |
|---|---|
| `core/aiuda_core/` | El dominio, sin HTTP: modelos SQLAlchemy, motor HITL (proponer, aprobar, enviar, conciliar), conectores, CUA, cifrado. No importa `server/`. |
| `server/aiuda_server/` | La capa local: API FastAPI, jobs (`worker/main.py`, funciones síncronas), scheduler, sondeo de WhatsApp entrante, CLI, consola embebida. |
| `web/` | Consola Next.js 16 y Tailwind v4. Se exporta estática (`npm run export`) y viaja dentro del wheel. |
| `desktop/` | App Tauri: ventana y ciclo de vida del sidecar. Nada de lógica de negocio. |
| `packaging/` | `aiuda.spec` de PyInstaller: el server y la consola en un ejecutable. |
| `landing/` | Página pública estática. |
| `scripts/` | `build-app.sh`, `dev.sh`, `seed.py`, `cua_demo.py`. |

## Decisiones que definen el diseño

- **Humano en el loop, por diseño.** Los ayudantes leen y PROPONEN; nada sale sin
  aprobación. La "autonomía total" no existe a propósito.
- **Tus fuentes mandan.** aiuda no es el sistema de registro: lee con procedencia
  (cada dato sabe de qué fuente viene) y el write-back regresa a la fuente.
- **Local-first en serio.** El default no necesita variables de entorno, Docker,
  Redis ni migraciones: SQLite, `create_all` idempotente y la llave en
  `~/.aiuda/key`. El modo cliente-servidor se conserva (HTTP interno), así que la
  app de escritorio y una instancia operada por un integrador usan este mismo
  código.
- **BYO-IA.** aiuda no incluye ni revende inferencia. API key, suscripción
  personal (bajo tu riesgo, la UI lo dice) o un modelo local con Ollama, la única
  vía donde ningún dato sale de tu máquina. Ver [docs/IA.md](docs/IA.md).
- **Canales honestos.** WhatsApp con tu número (protocolo de WhatsApp Web, el
  aviso vive en la UI) o correo IMAP/SMTP. La Cloud API oficial de Meta existe
  como conector, pero necesita URL pública: es para instancias operadas, no para
  el local puro.
- **Un solo log de lo soberano.** Cada aprobación, rechazo, edición y write-back
  deja fila en `audit_logs`. Poder demostrar quién autorizó un cobro es
  fundacional.

## El camino de un recordatorio

Es el flujo más maduro y el molde de los demás.

1. **Sincronizar.** El conector trae la cartera con procedencia
   (`connectors/`, `engine/sync.py`).
2. **Clasificar.** `cartera/aging.py` pone cada factura en un bucket contra su
   fecha de vencimiento: `por_vencer` (más de 3 días), `vence_pronto` (0 a 3),
   `vencida_reciente` (1 a 15 días de atraso), `vencida` (16 a 45), `critica`
   (más de 45).
3. **Elegir el tono.** `cartera/tone.py` lo decide por bucket, en código: amable,
   amable directo, firme, o urgente con escalamiento. En `critica` el ayudante no
   negocia solo, avisa que el dueño va a contactar.
4. **Redactar.** El modelo escribe el mensaje respetando tono, historial y voz
   del negocio. El LLM redacta; el código decide qué se puede enviar.
5. **Aprobar.** El recordatorio vive una máquina de estados en la base
   (`engine/approval.py`): `draft` a `pending_approval` a `approved` a `sent`,
   con `rejected` y `failed` como salidas. Solo esas transiciones existen y el
   modelo no puede saltárselas.
6. **Enviar.** Por WhatsApp o correo, y cada envío queda registrado.
7. **Cobrar y regresar.** El pago detectado entra a conciliación, el dueño
   confirma y el write-back lo asienta en la fuente (`engine/writeback.py`,
   patrón outbox).

## Trabajos de fondo

No hay Redis, ni cola, ni proceso aparte. Dos hilos dentro del mismo proceso: uno
dispara la corrida de cobranza al minuto 0 de cada hora (idempotente y con
cooldowns, así que correr de más no duplica nada) y otro sondea WhatsApp entrante
cada 20 segundos. Si la computadora estaba apagada, la corrida siguiente se pone
al día. `aiuda daily` hace lo mismo en primer plano.

Las tareas que dispara un request (redactar ahora, por ejemplo) corren inline con
`BackgroundTasks` en este mismo proceso, después de responder.

## Base de datos

SQLite en `~/.aiuda/aiuda.db` con WAL. Sin Alembic: el esquema se declara en los
modelos y `create_all` lo materializa al arrancar, de forma idempotente. Por eso
la configuración nueva va en `Tenant.config` (JSON) en vez de columnas nuevas.

Todas las tablas conservan `tenant_id`: permite aislar workspaces en una
instancia operada y evita una migración destructiva. En local hay un workspace
y se crea solo; `WORKSPACE_ID` elige cuando una base importada trae varios.

Postgres sigue soportado con `DATABASE_URL` y el extra `aiuda-server[postgres]`,
para instancias operadas. El `Dockerfile` de la raíz es para ese caso, no para
la instalación normal.

## Tests

`core/tests` y `server/tests`: SQLite en memoria, LLM mockeado, deterministas y
sin necesidad de credenciales. `evals/` corre evaluaciones de IA aparte del gate.
CI: pytest, ruff, tsc, export de la consola y build de los wheels.

## Después de v0.1: nodo local y relay opcional

v0.1 sigue siendo un solo proceso local. La dirección futura toma de
[Buzz](https://github.com/block/buzz/blob/main/VISION_AGENT.md) una frontera,
no su producto completo:

- **aiuda node**, en la computadora del negocio: ejecuta la IA y los conectores,
  guarda las credenciales y devuelve propuestas.
- **relay opcional**: coordina trabajos, presencia del nodo, permisos,
  aprobaciones y acceso móvil o remoto. No ejecuta la IA ni guarda sus llaves,
  e.firma o credenciales de conectores.

El login aparece únicamente al activar acceso remoto. Sin relay, aiuda conserva
el arranque local sin cuenta. Un relay propio se conecta por URL o invitación,
sin cuenta de Hanova, y el nodo se autentica con su propia llave.

Por la sensibilidad fiscal, el relay debe guardar metadatos mínimos o contenido
cifrado de extremo a extremo que el operador no pueda abrir. Antes de compartir
infraestructura entre negocios, el camino operable es una instancia dedicada
por cliente; el aislamiento compartido no es objetivo de v0.1.
