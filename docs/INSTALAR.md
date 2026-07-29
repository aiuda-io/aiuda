# Instalar aiuda

Dos caminos para lo mismo: la app de escritorio (sin terminal) y la instalación
desde el código. Los dos arrancan el mismo motor local en `127.0.0.1:4747` y
guardan todo en `~/.aiuda/`.

## App de escritorio

La app no es un producto aparte: empaqueta el server local, lo arranca al abrir
y lo apaga al cerrar. Trae Python adentro, no hay que instalar nada más.

Todavía no publicamos un release en GitHub. Para conseguirla:

- Pídela a consulting@hanova.mx (instalador de macOS con chip Apple).
- O constrúyela tú (ver abajo).

### macOS: el aviso de "desarrollador no identificado"

La app está firmada de punta a punta, pero con una firma **sin identidad**:
todavía no compramos el certificado de Apple, y sin él tampoco se puede
notarizar. macOS lo nota y avisa la primera vez. Para abrirla:

1. Abre el `.dmg` y arrastra **aiuda** a Aplicaciones.
2. En Aplicaciones, clic derecho sobre aiuda y elige **Abrir** (no doble clic).
3. En el diálogo, **Abrir** otra vez. Esto solo se hace la primera vez.

Eso es todo: no hay que escribir nada en ninguna terminal.

Si tienes un instalador de **antes del 27 de julio de 2026**, bórralo. Esos
salían mal firmados y macOS los reportaba como **"dañados"**, que no es lo mismo
que sin firmar: el sistema mataba la app al abrirla y el clic derecho no la
salvaba. Ya está arreglado. Si te aparece ese mensaje con un instalador nuevo,
entonces sí es que el archivo se corrompió al bajarlo: vuelve a descargarlo.

### Windows y Linux

El flujo de release construye el instalador `.exe` (NSIS) de Windows y el `.deb`
y `.AppImage` de Linux, pero nadie los ha probado todavía. En Windows,
SmartScreen mostrará "Windows protegió tu PC":
**Más información** y luego **Ejecutar de todas formas**. Si algo no funciona
ahí, es información útil para un issue.

### Construir la app

Necesitas node, uv y Rust (`rustup`).

```sh
scripts/build-app.sh                 # consola + binario + instaladores
scripts/build-app.sh --solo-binario  # solo el ejecutable del server
```

Los instaladores salen en `desktop/src-tauri/target/release/bundle/` y el
binario suelto en `dist/bin/aiuda`.

### Desinstalar

Borra la app y borra `~/.aiuda/` (ahí están tus datos). No queda nada más: no
hay servicios instalados, ni cuentas, ni archivos en el sistema. Ver
[DATOS.md](DATOS.md) antes, por si quieres respaldar.

## Desde el código

Python 3.11+ y [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/aiuda-io/aiuda && cd aiuda
uv sync
cd web && npm ci && npm run export && cd ..   # la consola, una vez
uv run aiuda start
```

`aiuda start` abre el navegador en la consola con un token de sesión que cambia
en cada arranque. Comandos disponibles:

| Comando | Qué hace |
|---|---|
| `aiuda start` | API, consola y scheduler en `127.0.0.1:4747` |
| `aiuda daily` | Corre la corrida de cobranza ahora, en primer plano |
| `aiuda doctor` | Revisa la instalación y dice qué falta |
| `aiuda version` | Versión instalada |

Banderas útiles de `start`: `--port`, `--no-browser`, `--no-token` (sin guardia,
solo para desarrollo) y `--quiet`.

El paso de `npm run export` es lo que construye la consola. Si lo saltas, el API
corre igual pero la raíz avisa que no hay consola.

### Extras opcionales

```sh
uv sync --extra cua                       # navegador para portales sin API
.venv/bin/playwright install chromium     # el Chromium, una vez
```

Datos de demostración deterministas, para ver la consola con contenido:

```sh
uv run python scripts/seed.py             # sembrar
uv run python scripts/seed.py --wipe      # borrar solo lo sembrado
```

## Qué necesitas antes de que sirva de algo

Instalar no basta: aiuda necesita una IA y una fuente de datos.

- **IA:** el Claude Code o el Codex que ya tengas instalado, una llave, tu
  suscripción o un modelo local. Ver [IA.md](IA.md).
- **Fuente:** tu Odoo, un Excel o cualquier API con el conector a la medida. Se
  conecta desde la consola.
- **Canal (opcional):** WhatsApp con tu número (necesita
  [wacli](https://github.com/steipete/wacli)) o correo IMAP/SMTP.

## El manual va adentro

No hay que buscar nada en internet: este manual viaja dentro de aiuda. En la
consola, arriba a la derecha, dice **Manual**. Funciona sin conexión, igual que
todo lo demás, y es el mismo texto de esta carpeta.

Si algo no arranca, [PROBLEMAS.md](PROBLEMAS.md).
